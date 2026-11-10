"""Replaced chunks supersede their open offers and drafts (INK-199, decision 0114). Pure sqlite."""

import sqlite3

from inkbridge.db import offers as offers_db
from inkbridge.db import ops as ops_db
from inkbridge.db.common import _now
from inkbridge.db.regions import get_region, list_regions
from inkbridge.db.sync import _live_successor

OVERLAP = 0.5  # intersection over the smaller box; hypothesis


def active_chunks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Active chunks the user wrote (an agent's answer is never a replacement)."""
    rows = list_regions(conn, document_id, chunks=True, status="active", limit=500)
    return [c for c in rows if c["source"] != "agent"]


def _overlap(a: dict, b: dict) -> bool:
    ix = max(0.0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    small = min(a["width"] * a["height"], b["width"] * b["height"])
    return small > 0 and ix * iy / small >= OVERLAP


def replacement(
    conn: sqlite3.Connection, document_id: str, chunk_id: str, active: list[dict]
) -> str | None:
    """Live chunk that took over an orphaned one: its successor chain, else an active
    reader-written chunk on top of it. None for an active chunk, a deleted-ink orphan, or an
    unknown id."""
    row = get_region(conn, chunk_id)
    if row is None or row["document_id"] != document_id or row["status"] == "active":
        return None
    live = _live_successor(conn, row, document_id)
    if live:
        return live["id"]
    return next((c["id"] for c in active if _overlap(row["bounds"], c["bounds"])), None)


def line_of(conn: sqlite3.Connection, document_id: str, chunk_id: str, active: list[dict]) -> str:
    """The id an anchor stands for today: itself when active, else its replacement, else itself."""
    return replacement(conn, document_id, chunk_id, active) or chunk_id


def run(conn: sqlite3.Connection, document_id: str) -> tuple[list[dict], list[dict]]:
    """Expire open offers and reject/expire unaccepted drafts whose anchor was replaced.

    Returns (offers, ops) changed. Accepted ops are never touched.
    """
    active = active_chunks(conn, document_id)
    offer_ids: list[str] = []
    op_ids: list[str] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        now = _now()
        for o in offers_db.list_offers(conn, document_id, "open"):
            if replacement(conn, document_id, o["anchor_chunk"], active) is not None:
                conn.execute(
                    "UPDATE offers SET status='expired', resolved_at=? WHERE id=?", (now, o["id"])
                )
                offer_ids.append(o["id"])
        rows = conn.execute(
            "SELECT id, status FROM agent_ops WHERE document_id=?"
            " AND status IN ('placed','pending','delivered')",
            (document_id,),
        ).fetchall()
        for r in rows:
            op = ops_db.get_op(conn, r["id"])
            anchor = op["payload"].get("anchor_resolved") or op["payload"].get("anchor")
            if (
                not isinstance(anchor, str)
                or replacement(conn, document_id, anchor, active) is None
            ):
                continue
            status = "rejected" if r["status"] == "placed" else "expired"
            conn.execute(
                "UPDATE agent_ops SET status=?, resolved_at=?, error='superseded' WHERE id=?",
                (status, now, r["id"]),
            )
            op_ids.append(r["id"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return [offers_db.get_offer(conn, i) for i in offer_ids], [
        ops_db.get_op(conn, i) for i in op_ids
    ]
