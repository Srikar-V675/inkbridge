"""Agent write queue (`agent_ops`). Agents can only add elements: never edit or delete ink.

Two checks hold invariant N1 here, not in the client:
- an op payload may not name any element id that exists in the stored scene (ExistingElementIds);
- the elements the browser measured for an op must carry new ids issued for this op: each starts
  with the op's `id_prefix` (db/drafts.py). Drafts live in the op row until Accept, so a Reject
  never touches the scene.

Lifecycle: pending | delivered -> placed -> accepted | rejected, accepted -> placed (unaccept),
plus failed and expired. `placed`, `accepted` and the unaccept return are set only by db/drafts.py.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from inkbridge.agent import placement
from inkbridge.canvas.chunker import proximity_threshold
from inkbridge.canvas.hashes import bbox_of
from inkbridge.db.common import DocumentNotFound, _now
from inkbridge.db.documents import document_exists, get_scene

OP_TYPES = ("write_text", "draw_diagram")
STATUSES = ("pending", "delivered", "placed", "accepted", "rejected", "failed", "expired")
# Ops whose elements may not be in the stored scene yet still reserve their spot.
_RESERVING = ("pending", "delivered", "placed")
_TRANSITIONS = {
    "pending": {"delivered", "failed", "expired"},
    "delivered": {"failed", "expired"},
    "placed": {"accepted", "rejected"},
    "accepted": {"placed"},
}
_DRAFTS_ONLY = ("placed", "accepted")  # reachable through db/drafts.py, never through update_status


class ExistingElementIds(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"payload references existing elements: {ids}")
        self.ids = ids


class AnchorNotFound(Exception):
    pass


class AnchorGone(AnchorNotFound):
    """The anchor chunk was deleted and no live successor remains (INK-084)."""


class OpNotFound(Exception):
    pass


MAX_OPEN_OPS = 200  # pending or delivered per canvas: an agent loop cannot queue drafts forever
OP_TTL_S = 24 * 3600  # pending/delivered ops older than this are expired, never drawn (INK-088)


class TooManyOpen(Exception):
    """The canvas already has MAX_OPEN_OPS ops that no browser has drawn yet."""

    def __init__(self, document_id: str, count: int, since: str | None):
        super().__init__(document_id)
        self.count, self.since = count, since


class OpConflict(Exception):
    """Same op_id posted again with a different body."""


class InvalidTransition(Exception):
    def __init__(self, current: str, wanted: str):
        super().__init__(f"op is {current}, cannot become {wanted}")
        self.current = current


def _strings(value: Any) -> set[str]:
    """Every string anywhere in value, dict keys included (iterative: any nesting depth)."""
    out: set[str] = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            stack += list(v.keys()) + list(v.values())
        elif isinstance(v, list):
            stack += v
    return out


def id_prefix(op_id: str) -> str:
    """Every element an op creates has an id starting with this. Op ids never contain ':', so no
    op's prefix is a prefix of another's."""
    return f"{op_id}:"


def referenced_existing_ids(payload: Any, elements: list[dict]) -> list[str]:
    """Element ids of the scene (deleted ones too) that appear anywhere in the payload."""
    return sorted(_strings(payload) & {e["id"] for e in elements})


def _row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "type": row["type"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
        "created_at": row["created_at"],
        "elements": json.loads(row["elements_json"]) if row["elements_json"] else None,
        "box": json.loads(row["box_json"]) if row["box_json"] else None,
        "resolved_at": row["resolved_at"],
        **{k: row[k] for k in ("question_id", "task_id", "offer_id", "revises", "diagram_id")},
    }


def _scene_elements(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    # Tombstone stubs count: an element deleted long ago still holds its id (INK-110, decision 0077).
    _, elements_json = get_scene(conn, document_id, stubs=True)
    return json.loads(elements_json)


def check_payload(conn: sqlite3.Connection, document_id: str, payload: Any) -> None:
    """Raise ExistingElementIds if the raw payload names any element of the stored scene."""
    ids = referenced_existing_ids(payload, _scene_elements(conn, document_id))
    if ids:
        raise ExistingElementIds(ids)


def create_op(
    conn: sqlite3.Connection,
    document_id: str,
    op_type: str,
    payload: dict[str, Any],
    op_id: str | None = None,
    expired: list[dict] | None = None,
) -> tuple[dict, bool]:
    """Enqueue an op with a server-computed placement; return (op, created).

    `expired`, if given, receives the stale ops the sweep expired (only when the call commits).

    The caller has validated the payload's shape. Runs under one write lock so two ops posted
    at once see each other's reserved spot.
    """
    if op_type not in OP_TYPES:
        raise ValueError(f"unknown op type {op_type!r}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _create_op(conn, document_id, op_type, payload, op_id, expired)
    except BaseException:
        conn.rollback()
        raise


def _expire_stale(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Caller owns the transaction. Returns the ops it just expired (id, document_id, status, error).

    Placed ops are kept: their drafts are held in the op awaiting Accept or Reject. The db layer
    only reports; the API layer pushes `op.updated` for each (it must not import the hub).
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=OP_TTL_S)).isoformat()
    rows = conn.execute(
        "UPDATE agent_ops SET status = 'expired' WHERE document_id = ?"
        " AND status IN ('pending', 'delivered') AND created_at IS NOT NULL AND created_at < ?"
        " RETURNING id, document_id, status, error",
        (document_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def _stroke_heights(elements: list[dict], anchor_ids: set[str] | None) -> list[float]:
    """Heights of the user's live freedraw strokes (drafts and agent ink never count)."""
    out = []
    for e in elements:
        if e.get("type") != "freedraw" or e.get("isDeleted") or not e.get("points"):
            continue
        cd = e.get("customData") or {}
        if cd.get("draft") or cd.get("author") == "agent":
            continue
        if anchor_ids is not None and e["id"] not in anchor_ids:
            continue
        ys = [p[1] for p in e["points"]]
        out.append(max(ys) - min(ys))
    return out


LATEST_STROKES = 50  # scale sample when the anchor has too few strokes


def _sample_heights(elements: list[dict], anchor_ids: set[str] | None) -> list[float]:
    heights = _stroke_heights(elements, anchor_ids) if anchor_ids else []
    if len(heights) < placement.MIN_SAMPLES:
        heights = _stroke_heights(elements, None)[-LATEST_STROKES:]  # scene order = write order
    return heights


def _resolve_anchor(conn, document_id, region_id):
    """The anchor chunk, or its live successor when a re-chunk orphaned it (INK-081).

    An orphan with no live successor is refused (AnchorGone): its box is deleted ink.
    Read-only on regions.
    """
    seen = set()
    while region_id not in seen:
        seen.add(region_id)
        row = conn.execute(
            "SELECT id, bbox, element_ids_json, status, successor_of FROM regions"
            " WHERE id = ? AND document_id = ?",
            (region_id, document_id),
        ).fetchone()
        if row is None or not row["bbox"]:
            raise AnchorNotFound(region_id)
        if row["status"] == "active":
            return row
        if not row["successor_of"]:
            raise AnchorGone(region_id)
        region_id = row["successor_of"]
    raise AnchorGone(region_id)  # successor cycle


def reserved_boxes(
    conn: sqlite3.Connection, document_id: str, exclude_op: str | None = None
) -> tuple[list[placement.Box], placement.Box | None]:
    """Spots held by other open drafts: (boxes to avoid, the most recent one).

    pending/delivered ops reserve their estimate; placed ops their real measured box.
    """
    occupied: list[placement.Box] = []
    recent: placement.Box | None = None
    for row in conn.execute(
        "SELECT id, type, payload_json, status, box_json FROM agent_ops WHERE document_id = ?"
        f" AND status IN ({','.join('?' * len(_RESERVING))}) ORDER BY created_at, rowid",
        (document_id, *_RESERVING),
    ):
        if row["id"] == exclude_op:
            continue
        other = json.loads(row["payload_json"])
        if row["status"] == "placed" and row["box_json"]:
            box: placement.Box = json.loads(row["box_json"])
        elif "placement" in other:
            w, h = placement.estimate_size(row["type"], other)
            box = {**other["placement"], "width": w, "height": h}
        else:
            continue
        occupied.append(box)
        recent = box
    return occupied, recent


def _create_op(conn, document_id, op_type, payload, op_id, expired=None):
    payload = {k: v for k, v in payload.items() if k != "anchor_resolved"}  # server-set only
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    if op_id is not None:
        row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op_id,)).fetchone()
        if row is not None:
            existing = _row_dict(row)
            stored = {
                k: v
                for k, v in existing["payload"].items()
                if k not in ("placement", "id_prefix", "font_size", "wrap_chars", "anchor_resolved")
            }
            if (existing["document_id"], existing["type"], stored) != (
                document_id,
                op_type,
                payload,
            ):
                raise OpConflict(op_id)
            conn.rollback()
            return existing, False
    swept = _expire_stale(conn, document_id)  # an expired op must not hold a slot
    open_ops, oldest = conn.execute(
        "SELECT COUNT(*), MIN(created_at) FROM agent_ops WHERE document_id = ?"
        " AND status IN ('pending', 'delivered')",
        (document_id,),
    ).fetchone()
    if open_ops >= MAX_OPEN_OPS:
        raise TooManyOpen(document_id, open_ops, oldest)
    elements = _scene_elements(conn, document_id)
    ids = referenced_existing_ids(payload, elements)
    oid = op_id or uuid.uuid4().hex[:12]
    ids += sorted(e["id"] for e in elements if e["id"].startswith(id_prefix(oid)))
    if ids:
        raise ExistingElementIds(ids)

    anchor = None
    anchor_ids = None
    if payload.get("anchor") is not None:
        region = _resolve_anchor(conn, document_id, payload["anchor"])
        payload = {**payload, "anchor_resolved": region["id"]}
        anchor = json.loads(region["bbox"])
        anchor_ids = set(json.loads(region["element_ids_json"] or "[]"))

    fs = placement.font_size_for(_sample_heights(elements, anchor_ids), payload.get("size"))
    payload = {**payload, "font_size": fs, "wrap_chars": placement.WRAP_CHARS}

    occupied = [
        placement.rotated_box(bbox_of([e]), e.get("angle") or 0)
        for e in elements
        if not e.get("isDeleted")
    ]
    extra, recent = reserved_boxes(conn, document_id)
    occupied += extra
    clear = proximity_threshold(elements)
    spot = placement.place(
        occupied, placement.estimate_size(op_type, payload), anchor, fs, clear, recent
    )

    conn.execute(
        "INSERT INTO agent_ops (id, document_id, type, payload_json, status, created_at)"
        " VALUES (?, ?, ?, ?, 'pending', ?)",
        (
            oid,
            document_id,
            op_type,
            json.dumps({**payload, "placement": spot, "id_prefix": id_prefix(oid)}),
            _now(),
        ),
    )
    conn.commit()
    if expired is not None:
        expired.extend(swept)
    return get_op(conn, oid), True


def op_exists(conn: sqlite3.Connection, op_id: str) -> bool:
    return conn.execute("SELECT 1 FROM agent_ops WHERE id = ?", (op_id,)).fetchone() is not None


def get_op(conn: sqlite3.Connection, op_id: str) -> dict:
    row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op_id,)).fetchone()
    if row is None:
        raise OpNotFound(op_id)
    return _row_dict(row)


def list_ops(
    conn: sqlite3.Connection,
    document_id: str,
    statuses: list[str] | None = None,
    expired: list[dict] | None = None,
) -> list[dict]:
    """`expired`, if given, receives the stale ops this call's sweep expired."""
    if not conn.in_transaction:  # the sweep writes; a caller already in a transaction keeps its own
        conn.execute("BEGIN IMMEDIATE")
        try:
            swept = _expire_stale(conn, document_id)
            conn.commit()
            if expired is not None:
                expired.extend(swept)
        except BaseException:
            conn.rollback()
            raise
    sql = "SELECT * FROM agent_ops WHERE document_id = ?"
    args: list = [document_id]
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += statuses
    sql += " ORDER BY created_at, rowid"
    return [_row_dict(r) for r in conn.execute(sql, args)]


def update_status(
    conn: sqlite3.Connection,
    op_id: str,
    status: str,
    error: str | None = None,
) -> dict:
    """Move an op to failed or expired. Repeating the current status is a no-op.

    placed and accepted are refused here (InvalidTransition): see db/drafts.py.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _update_status(conn, op_id, status, error)
    except BaseException:
        conn.rollback()
        raise


def _update_status(conn, op_id, status, error):
    op = get_op(conn, op_id)
    current = op["status"]
    if status == current:
        conn.rollback()
        return op
    if status in _DRAFTS_ONLY or status not in _TRANSITIONS.get(current, set()):
        raise InvalidTransition(current, status)
    conn.execute(
        "UPDATE agent_ops SET status = ?, error = COALESCE(?, error) WHERE id = ?",
        (status, error if status == "failed" else None, op_id),
    )
    conn.commit()
    return get_op(conn, op_id)


def mark_delivered(conn: sqlite3.Connection, op_id: str) -> bool:
    """Called when the op was pushed to a browser. Only a pending op moves; True if this call
    moved it (False if it was already delivered, placed or resolved)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE agent_ops SET status = 'delivered' WHERE id = ? AND status = 'pending'",
            (op_id,),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return cur.rowcount == 1
