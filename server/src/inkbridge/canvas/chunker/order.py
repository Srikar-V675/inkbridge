"""Reading order and a kind hint for chunks."""

import statistics
from typing import Any

from inkbridge.canvas.chunker.config import _SHAPES, is_draft


def reading_order(boxes: dict[str, dict[str, float]]) -> list[str]:
    """Order chunk ids for reading: rows top to bottom, each row left to right.

    Chunks whose vertical centres lie within 0.5 of the median chunk height share a row, so a
    diagram laid out left to right reads left to right even when tops differ slightly.
    """
    if not boxes:
        return []
    tolerance = 0.5 * statistics.median(b["height"] for b in boxes.values())
    by_top = sorted(boxes, key=lambda i: (boxes[i]["y"], boxes[i]["x"], i))
    rows: list[list[str]] = []
    centres: list[list[float]] = []
    for cid in by_top:
        centre = boxes[cid]["y"] + boxes[cid]["height"] / 2
        if rows and abs(centre - statistics.fmean(centres[-1])) <= tolerance:
            rows[-1].append(cid)
            centres[-1].append(centre)
        else:
            rows.append([cid])
            centres.append([centre])
    return [cid for row in rows for cid in sorted(row, key=lambda i: (boxes[i]["x"], i))]


def kind_hint(elements: list[dict[str, Any]]) -> str:
    """handwriting / diagram / mixed from element types. A hint only, never used to decide."""
    live = [e for e in elements if not e.get("isDeleted") and not is_draft(e)]
    shapes = sum(1 for e in live if e.get("type") in _SHAPES)
    writing = sum(1 for e in live if e.get("type") in {"freedraw", "text"})
    if shapes == 0:
        return "handwriting"
    if writing == 0:
        return "diagram"
    return "mixed"
