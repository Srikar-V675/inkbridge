"""Agent write queue (`agent_ops`). Agents can only add elements: never edit or delete ink.

Two checks hold invariant N1 here, not in the client:
- an op payload may not name any element id that exists in the stored scene (ExistingElementIds);
- the ids the browser reports for an applied op must be new ids issued for this op: each starts
  with the op's `id_prefix`, which no element had when the op was enqueued. Reject removes exactly
  an op's recorded ids, so a user element recorded here would be deleted by a Reject. A prefix
  (rather than trusting customData tags, which any client can write) means a user element can
  only be claimed if the client renamed it, which is a client bug, not an agent capability.

Lifecycle: pending -> delivered -> applied -> accepted | rejected, plus failed and expired.
"""

import json
import sqlite3
import uuid
from typing import Any

from inkbridge import placement
from inkbridge.db import DocumentNotFound, _now, document_exists, get_scene
from inkbridge.regions import bbox_of

OP_TYPES = ("write_text", "draw_diagram")
STATUSES = ("pending", "delivered", "applied", "accepted", "rejected", "failed", "expired")
# Ops whose elements may not be in the stored scene yet still reserve their spot.
_RESERVING = ("pending", "delivered", "applied")
_TRANSITIONS = {
    "pending": {"delivered", "applied", "failed", "expired"},
    "delivered": {"applied", "failed", "expired"},
    "applied": {"accepted", "rejected"},
}


class ExistingElementIds(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"payload references existing elements: {ids}")
        self.ids = ids


class AnchorNotFound(Exception):
    pass


class OpNotFound(Exception):
    pass


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
    }


def _scene_elements(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    _, elements_json = get_scene(conn, document_id)
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
) -> tuple[dict, bool]:
    """Enqueue an op with a server-computed placement; return (op, created).

    The caller has validated the payload's shape. Runs under one write lock so two ops posted
    at once see each other's reserved spot.
    """
    if op_type not in OP_TYPES:
        raise ValueError(f"unknown op type {op_type!r}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _create_op(conn, document_id, op_type, payload, op_id)
    except BaseException:
        conn.rollback()
        raise


def _create_op(conn, document_id, op_type, payload, op_id):
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    if op_id is not None:
        row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op_id,)).fetchone()
        if row is not None:
            existing = _row_dict(row)
            stored = {
                k: v for k, v in existing["payload"].items() if k not in ("placement", "id_prefix")
            }
            if (existing["document_id"], existing["type"], stored) != (
                document_id,
                op_type,
                payload,
            ):
                raise OpConflict(op_id)
            conn.rollback()
            return existing, False
    elements = _scene_elements(conn, document_id)
    ids = referenced_existing_ids(payload, elements)
    oid = op_id or uuid.uuid4().hex[:12]
    ids += sorted(e["id"] for e in elements if e["id"].startswith(id_prefix(oid)))
    if ids:
        raise ExistingElementIds(ids)

    anchor = None
    if payload.get("anchor") is not None:
        region = conn.execute(
            "SELECT bbox FROM regions WHERE id = ? AND document_id = ?",
            (payload["anchor"], document_id),
        ).fetchone()
        if region is None or not region["bbox"]:
            raise AnchorNotFound(payload["anchor"])
        anchor = json.loads(region["bbox"])

    occupied = [
        placement.rotated_box(bbox_of([e]), e.get("angle") or 0)
        for e in elements
        if not e.get("isDeleted")
    ]
    for row in conn.execute(
        f"SELECT type, payload_json FROM agent_ops WHERE document_id = ?"
        f" AND status IN ({','.join('?' * len(_RESERVING))})",
        (document_id, *_RESERVING),
    ):
        other = json.loads(row["payload_json"])
        if "placement" in other:
            w, h = placement.estimate_size(row["type"], other)
            occupied.append({**other["placement"], "width": w, "height": h})
    spot = placement.place(occupied, placement.estimate_size(op_type, payload), anchor)

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
    return get_op(conn, oid), True


def op_exists(conn: sqlite3.Connection, op_id: str) -> bool:
    return conn.execute("SELECT 1 FROM agent_ops WHERE id = ?", (op_id,)).fetchone() is not None


def get_op(conn: sqlite3.Connection, op_id: str) -> dict:
    row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op_id,)).fetchone()
    if row is None:
        raise OpNotFound(op_id)
    return _row_dict(row)


def list_ops(
    conn: sqlite3.Connection, document_id: str, statuses: list[str] | None = None
) -> list[dict]:
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
    element_ids: list[str] | None = None,
    error: str | None = None,
) -> dict:
    """Move an op along its lifecycle. Repeating the current status is a no-op."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        return _update_status(conn, op_id, status, element_ids, error)
    except BaseException:
        conn.rollback()
        raise


def _update_status(conn, op_id, status, element_ids, error):
    op = get_op(conn, op_id)
    current = op["status"]
    if status == current:
        if status == "applied" and set(op["result"]["element_ids"]) != set(element_ids or []):
            raise InvalidTransition(current, status)
        conn.rollback()
        return op
    if status not in _TRANSITIONS.get(current, set()):
        raise InvalidTransition(current, status)
    result_json = None
    if status == "applied":
        _check_new_ids(op, element_ids or [])
        result_json = json.dumps({"element_ids": element_ids})
    conn.execute(
        "UPDATE agent_ops SET status = ?, result_json = COALESCE(?, result_json),"
        " error = COALESCE(?, error) WHERE id = ?",
        (status, result_json, error if status == "failed" else None, op_id),
    )
    conn.commit()
    return get_op(conn, op_id)


def _check_new_ids(op: dict, ids: list[str]) -> None:
    """Every acked id must be one issued for this op. Its own drafts may already be autosaved."""
    taken = sorted(i for i in ids if not i.startswith(op["payload"]["id_prefix"]))
    if taken:
        raise ExistingElementIds(taken)


def mark_delivered(conn: sqlite3.Connection, op_id: str) -> dict:
    """Called when the op is pushed to a browser (INK-042). Only a pending op moves."""
    conn.execute(
        "UPDATE agent_ops SET status = 'delivered' WHERE id = ? AND status = 'pending'", (op_id,)
    )
    conn.commit()
    return get_op(conn, op_id)
