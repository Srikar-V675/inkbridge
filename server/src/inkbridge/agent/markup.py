"""Mark-up as instruction (INK-141, decision 0102): ink drawn over an accepted agent diagram.

Read-only over the scene: finds ink and renders a crop; it never writes elements.
"""

import json
import sqlite3
from datetime import datetime, timedelta

from inkbridge.canvas import raster
from inkbridge.db import ops as ops_db

MARKUP_WINDOW_S = 1800  # hypothesis: ink later than this after Accept is not read as mark-up
MARKUP_INK = "#D32F2F"  # crop only: new ink in red so the agent can tell it from the diagram

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


def _box(elements: list[dict]) -> Box | None:
    """Union bbox over x, y, width, height; None for an empty list."""
    if not elements:
        return None
    return (
        min(e["x"] for e in elements),
        min(e["y"] for e in elements),
        max(e["x"] + e.get("width", 0) for e in elements),
        max(e["y"] + e.get("height", 0) for e in elements),
    )


def _intersects(a: Box | None, b: Box | None) -> bool:
    """Boxes that overlap or touch."""
    if a is None or b is None:
        return False
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


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
    box = _box(diagram_elements(conn, diagram))
    if since is None or box is None:
        return []
    until = (
        None
        if window_s is None
        else (datetime.fromisoformat(since) + timedelta(seconds=window_s)).isoformat()
    )
    out = []
    for seq, updated, e in _live_rows(conn, diagram["document_id"]):
        if (e.get("customData") or {}).get("author") == "agent":
            continue
        if updated < since or (until is not None and updated > until):
            continue
        if _intersects(_box([e]), box):
            out.append((seq, e))
    return out


def render(conn: sqlite3.Connection, diagram: dict) -> bytes | None:
    """The diagram in its own colours with the new ink in red; None when nothing is drawable."""
    ink = ink_over(conn, diagram, window_s=None)
    els = diagram_elements(conn, diagram) + [{**e, "strokeColor": MARKUP_INK} for _, e in ink]
    return raster.render_crop(els)
