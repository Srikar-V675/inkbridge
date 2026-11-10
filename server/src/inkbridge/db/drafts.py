"""Agent drafts live in the op row until Accept (INK-114, decision 0086).

measure_op stores the browser-measured elements, placed with their true size. accept_op is the one
path allowed to write `<op_id>:` ids into the scene (merge_elements with strict=False); reject
writes nothing; unaccept removes only elements the user has not touched since Accept.
"""

import json
import math
import random
import sqlite3
from datetime import UTC, datetime
from typing import Any

from inkbridge.agent import flow, placement
from inkbridge.agent.attention import attention
from inkbridge.canvas import boxes
from inkbridge.canvas.hashes import bbox_of
from inkbridge.db import diagrams, scenes
from inkbridge.db.common import _now
from inkbridge.db.elements import _int
from inkbridge.db.ops import (
    ExistingElementIds,
    InvalidTransition,
    _scene_elements,
    get_op,
    list_ops,
    reserved_boxes,
)

MAX_OFFSET = 20_000  # |dx|, |dy| of an accept beyond this is refused
UNACCEPT_WINDOW_S = 60
MAX_MEASURED_ELEMENTS = 5_000


class IdCollision(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"ids already in the scene: {ids}")
        self.ids = ids


class BadPrefix(Exception):
    def __init__(self, element_id: str):
        super().__init__(f"id without the op prefix: {element_id}")
        self.id = element_id


class WindowClosed(Exception):
    pass


def _like(op_id: str) -> str:
    return op_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ":%"


def _as_draft(e: dict, op_id: str, dx: float, dy: float) -> dict:
    """Copy moved by (dx, dy); client customData is replaced, never merged."""
    return {
        **e,
        "x": e.get("x", 0) + dx,
        "y": e.get("y", 0) + dy,
        "customData": {"author": "agent", "op_id": op_id, "draft": True},
    }


def _anchor_box(conn: sqlite3.Connection, op: dict) -> placement.Box | None:
    row = conn.execute(
        "SELECT bbox FROM regions WHERE id = ? AND document_id = ? AND status = 'active'",
        (op["payload"].get("anchor_resolved"), op["document_id"]),
    ).fetchone()
    return json.loads(row["bbox"]) if row and row["bbox"] else None


def measure_op(
    conn: sqlite3.Connection, op_id: str, elements: Any, width: Any, height: Any
) -> dict:
    """Store the browser's elements for the op, placed with their true size; status `placed`."""
    if not (isinstance(elements, list) and 0 < len(elements) <= MAX_MEASURED_ELEMENTS):
        raise ValueError("elements")
    if not all(
        isinstance(v, int | float)
        and not isinstance(v, bool)
        and math.isfinite(v)
        and 0 < v <= 100_000
        for v in (width, height)
    ):
        raise ValueError("size")
    conn.execute("BEGIN IMMEDIATE")
    try:
        op = get_op(conn, op_id)
        if op["status"] == "placed":
            conn.rollback()
            return op  # idempotent
        if op["status"] not in ("pending", "delivered"):
            raise InvalidTransition(op["status"], "placed")
        prefix = op["payload"]["id_prefix"]
        ids = [e.get("id") for e in elements if isinstance(e, dict)]
        if len(ids) != len(elements) or len(set(ids)) != len(ids):
            raise ValueError("elements")
        taken = sorted(str(i) for i in ids if not (isinstance(i, str) and i.startswith(prefix)))
        scene = _scene_elements(conn, op["document_id"])
        stored = {e["id"] for e in scene}
        taken += sorted(i for i in ids if i in stored)
        if taken:
            raise ExistingElementIds(taken)
        occupied = [
            placement.rotated_box(bbox_of([e]), e.get("angle") or 0)
            for e in scene
            if not e.get("isDeleted")
        ]
        extra, recent = reserved_boxes(conn, op["document_id"], exclude_op=op_id)
        occupied += extra
        anchor = _anchor_box(conn, op)
        spot = placement.place(
            occupied,
            (float(width), float(height)),
            anchor,
            op["payload"]["font_size"],
            recent,
            placement.view_rect(attention.view(op["document_id"])),
            placement.connectors_of(scene),
        )
        box = bbox_of(elements)
        dx, dy = spot["x"] - box["x"], spot["y"] - box["y"]
        placed = [_as_draft(e, op_id, dx, dy) for e in elements]
        arrow = (
            flow.arrow_for(prefix, anchor, spot, (float(width), float(height))) if anchor else None
        )
        if arrow and arrow["id"] not in set(ids):
            placed.append(_as_draft(arrow, op_id, 0, 0))
        tag = {
            e["id"]: e["customData"]["node"]
            for e in elements
            if isinstance(e.get("customData"), dict)
            and isinstance(e["customData"].get("node"), str)
        }
        node_map: dict[str, list[str]] = {}
        for e in elements:
            n = tag.get(e["id"]) or tag.get(e.get("containerId"))
            if n:
                node_map.setdefault(n, []).append(e["id"])
        payload = {**op["payload"], **({"node_map": node_map} if node_map else {})}
        conn.execute(
            "UPDATE agent_ops SET status='placed', elements_json=?, box_json=?, payload_json=? WHERE id=?",
            (
                json.dumps(placed),
                json.dumps({**spot, "width": width, "height": height}),
                json.dumps(payload),
                op_id,
            ),
        )
        conn.commit()
        return get_op(conn, op_id)
    except BaseException:
        conn.rollback()
        raise


def list_drafts(
    conn: sqlite3.Connection, document_id: str, expired: list[dict] | None = None
) -> list[dict]:
    return list_ops(conn, document_id, ["placed"], expired)


def accept_op(
    conn: sqlite3.Connection, op_id: str, dx: float = 0.0, dy: float = 0.0
) -> tuple[dict, int]:
    """Move the op's drafts into the scene, offset by (dx, dy). Returns (op, seq); repeating is a no-op."""
    if not all(
        isinstance(v, int | float) and math.isfinite(v) and abs(v) <= MAX_OFFSET for v in (dx, dy)
    ):
        raise ValueError("offset")
    op = get_op(conn, op_id)
    if op["status"] == "accepted":
        return op, op["result"]["seq"]
    if op["status"] != "placed" or not op["elements"]:
        raise InvalidTransition(op["status"], "accepted")
    prefix, now = op["payload"]["id_prefix"], _now()
    out = []
    for e in op["elements"]:
        if not e["id"].startswith(prefix):
            raise BadPrefix(e["id"])
        cd = {k: v for k, v in (e.get("customData") or {}).items() if k != "draft"}
        out.append(
            {
                **e,
                "x": e["x"] + dx,
                "y": e["y"] + dy,
                "customData": {**cd, "author": "agent", "op_id": op_id},
                "strokeStyle": "solid",
                "opacity": 100,
                "version": _int(e.get("version")) + 1,
                "versionNonce": random.getrandbits(31) or 1,
                "isDeleted": False,
            }
        )

    # A revision's Accept also tombstones the previous op's elements. Invariant: this is the only
    # agent path that deletes, and the server enforces it here, not the client: only ids of the
    # previous op (`<prev_id>:`, rows read from the scene) and only while (version, nonce) still
    # equal the stamps recorded at its Accept, so anything the user touched stays (INK-140, 0100).
    prev = get_op(conn, op["revises"]) if op.get("revises") else None
    n_new = len(out)

    def guard(c):
        if get_op(c, op_id)["status"] != "placed":  # re-read under the write lock
            raise InvalidTransition(get_op(c, op_id)["status"], "accepted")
        marks = ",".join("?" * n_new)
        hit = [
            r["id"]
            for r in c.execute(
                f"SELECT id FROM scene_elements WHERE document_id=? AND id IN ({marks})",
                [op["document_id"], *[e["id"] for e in out[:n_new]]],
            )  # tombstones count
        ]
        if hit:
            raise IdCollision(sorted(hit))
        del out[n_new:]  # the guard may run again on a retry
        if prev and prev["status"] == "accepted" and prev["result"]:
            rows = {
                r["id"]: r
                for r in c.execute(
                    "SELECT id, version, nonce, json FROM scene_elements"
                    " WHERE document_id=? AND id LIKE ? ESCAPE '\\'",
                    [op["document_id"], _like(prev["id"])],
                )
            }
            for i, (v, n) in prev["result"]["stamps"].items():
                r = rows.get(i)
                if r is not None and (r["version"], r["nonce"]) == (
                    v,
                    n,
                ):  # user has not touched it
                    out.append(
                        {
                            **json.loads(r["json"]),
                            "isDeleted": True,
                            "version": v + 1,
                            "versionNonce": random.getrandbits(31) or 1,
                        }
                    )

    def finish(c, head):
        stamps = {e["id"]: [e["version"], e["versionNonce"]] for e in out[:n_new]}
        # ids of live elements already overlapping the new shapes: ink that was there before
        # Accept, so touching it later is not mark-up (INK-141, decision 0102)
        mine = boxes.box(out[:n_new])
        near = []
        for r in c.execute(
            "SELECT id, json FROM scene_elements WHERE document_id=? AND is_deleted=0",
            (op["document_id"],),
        ):
            if r["id"] not in stamps and boxes.intersects(boxes.box([json.loads(r["json"])]), mine):
                near.append(r["id"])
        c.execute(
            "UPDATE agent_ops SET status='accepted', resolved_at=?, result_json=? WHERE id=?",
            (now, json.dumps({"seq": head, "stamps": stamps, "at": now, "near": near}), op_id),
        )
        if op.get("diagram_id"):
            diagrams.commit_version(c, op)

    try:
        r = scenes.merge_elements(
            conn, op["document_id"], out, strict=False, guard=guard, finish=finish
        )
    except InvalidTransition:
        op = get_op(conn, op_id)  # lost a race with another accept
        if op["status"] == "accepted":
            return op, op["result"]["seq"]
        raise
    return get_op(conn, op_id), r.seq


def reject_op(conn: sqlite3.Connection, op_id: str) -> tuple[dict, bool]:
    """Reject a placed op; no scene write. Returns (op, changed)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        op = get_op(conn, op_id)
        if op["status"] == "rejected":
            conn.rollback()
            return op, False
        if op["status"] != "placed":
            raise InvalidTransition(op["status"], "rejected")
        conn.execute(
            "UPDATE agent_ops SET status='rejected', resolved_at=? WHERE id=?", (_now(), op_id)
        )
        conn.commit()
        return get_op(conn, op_id), True
    except BaseException:
        conn.rollback()
        raise


def unaccept_op(conn: sqlite3.Connection, op_id: str) -> tuple[dict, list[str], list[str]]:
    """Take an accepted op back to `placed`: delete only elements unchanged since Accept."""
    op = get_op(conn, op_id)
    if op["status"] != "accepted":
        raise InvalidTransition(op["status"], "placed")
    if op.get("revises"):
        raise WindowClosed(
            op_id
        )  # shortcut: restoring the old version is out of scope (decision 0100)
    age = (datetime.now(UTC) - datetime.fromisoformat(op["result"]["at"])).total_seconds()
    if age > UNACCEPT_WINDOW_S:
        raise WindowClosed(op_id)
    stamps = op["result"]["stamps"]
    removed: list[str] = []
    kept: list[str] = []
    dead: list[dict] = []

    def guard(c):
        if get_op(c, op_id)["status"] != "accepted":
            raise InvalidTransition(get_op(c, op_id)["status"], "placed")
        removed.clear(), kept.clear(), dead.clear()
        rows = {
            r["id"]: r
            for r in c.execute(
                "SELECT id, version, nonce, json FROM scene_elements"
                " WHERE document_id=? AND id LIKE ? ESCAPE '\\'",
                [op["document_id"], _like(op_id)],
            )
        }
        for i, (v, n) in stamps.items():
            r = rows.get(i)
            if r is not None and (r["version"], r["nonce"]) == (v, n):  # untouched since accept
                e = json.loads(r["json"])
                dead.append(
                    {
                        **e,
                        "isDeleted": True,
                        "version": v + 1,
                        "versionNonce": random.getrandbits(31) or 1,
                    }
                )
                removed.append(i)
            else:
                kept.append(i)

    def finish(c, head):
        c.execute(
            "UPDATE agent_ops SET status='placed', resolved_at=NULL, result_json=NULL WHERE id=?",
            (op_id,),
        )

    scenes.merge_elements(conn, op["document_id"], dead, strict=False, guard=guard, finish=finish)
    return get_op(conn, op_id), list(removed), list(kept)
