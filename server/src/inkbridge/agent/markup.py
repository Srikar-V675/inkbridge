"""Mark-up as instruction (INK-141, decision 0102): ink drawn over an accepted agent diagram.

Read-only over the scene: finds ink and renders a crop; it never writes elements.
"""

import json
import sqlite3
from datetime import datetime, timedelta

from inkbridge.canvas import boxes, raster
from inkbridge.db import ops as ops_db

MARKUP_WINDOW_S = 1800  # hypothesis: ink later than this after Accept is not read as mark-up
MARKUP_INK = "#D32F2F"  # crop only: new ink in red so the agent can tell it from the diagram

_box, _intersects = boxes.box, boxes.intersects


def _live_rows(conn: sqlite3.Connection, document_id: str) -> list[tuple[int, str, dict]]:
    """(seq, updated_at, element) of every live element, in scene order."""
    rows = conn.execute(
        "SELECT seq, updated_at, json FROM scene_elements WHERE document_id=? AND is_deleted=0"
        " ORDER BY pos",
        (document_id,),
    ).fetchall()
    return [(r["seq"], r["updated_at"], json.loads(r["json"])) for r in rows]


def diagram_elements(conn: sqlite3.Connection, diagram: dict) -> list[dict]:
    """Live elements of the diagram's current op (`<op>:` ids)."""
    prefix = f"{diagram['current_op']}:"
    return [e for _, _, e in _live_rows(conn, diagram["document_id"]) if e["id"].startswith(prefix)]


def accepted_at(conn: sqlite3.Connection, diagram: dict) -> str | None:
    op = ops_db.get_op(conn, diagram["current_op"])
    return (op.get("result") or {}).get("at") or op.get("resolved_at")


def ink_over(
    conn: sqlite3.Connection, diagram: dict, *, window_s: int | None = MARKUP_WINDOW_S
) -> list[tuple[int, dict]]:
    """User ink drawn after the diagram was accepted whose box overlaps it, as (seq, element)."""
    since = accepted_at(conn, diagram)
    result = ops_db.get_op(conn, diagram["current_op"]).get("result") or {}
    near = result.get("near")  # ids that already overlapped the diagram at Accept; None = old op
    box = _box(diagram_elements(conn, diagram))
    if since is None or box is None:
        return []
    t0 = datetime.fromisoformat(since)
    until = None if window_s is None else t0 + timedelta(seconds=window_s)
    out = []
    for seq, updated, e in _live_rows(conn, diagram["document_id"]):
        if (e.get("customData") or {}).get("author") == "agent":
            continue
        if near is not None and e["id"] in near:
            continue  # old ink, even if the user nudged or recoloured it since
        t = datetime.fromisoformat(updated)
        if t < t0 or (until is not None and t > until):
            continue
        if _intersects(_box([e]), box):
            out.append((seq, e))
    return out


def render(conn: sqlite3.Connection, diagram: dict) -> bytes | None:
    """The diagram in its own colours with the new ink in red; None when nothing is drawable."""
    ink = ink_over(conn, diagram, window_s=None)
    els = diagram_elements(conn, diagram) + [{**e, "strokeColor": MARKUP_INK} for _, e in ink]
    return raster.render_crop(els)
