"""Where an agent op lands on the canvas. Pure: no I/O, no SQLite.

The server decides the position from the stored scene so it is deterministic and testable; the
browser only draws at it. Sizes are estimates (the browser lays text and Mermaid out), so the
"below everything" fallback is the one position that can never overlap whatever the true size.
"""

import math
import statistics
from typing import Any, TypedDict


class Box(TypedDict):
    x: float
    y: float
    width: float
    height: float


GAP = 40  # space left between an op and the ink it is placed beside
MARGIN = 16  # boxes closer than this count as overlapping

FONT_SIZE = 20  # legacy: ops stored before INK-066 carry no font_size
DEFAULT_FONT, MIN_FONT, MAX_FONT = 28, 18, 2000  # MAX is a sanity cap; size is relative to the ink
INK_TO_FONT = 1.5  # text size per px of median handwritten stroke height; tune on the tablet
MIN_SAMPLES = 3
WRAP_CHARS = 50  # server-set wrap width in characters; relative to the font by construction
SIZE_HINTS = {"small": 0.75, "normal": 1.0, "large": 1.5}
# Mermaid is laid out in the browser; reserve a generous box for a typical small flowchart.
DIAGRAM_SIZE = (600.0, 400.0)


def font_size_for(stroke_heights: list[float], hint: str | None = None) -> int:
    """Font size that reads beside handwriting whose strokes have these heights (px)."""
    heights = [h for h in stroke_heights if h > 0]
    base = statistics.median(heights) * INK_TO_FONT if len(heights) >= MIN_SAMPLES else DEFAULT_FONT
    return round(max(MIN_FONT, min(MAX_FONT, base * SIZE_HINTS.get(hint or "normal", 1.0))))


def gap_for(fs: float) -> float:
    return max(GAP, fs * 1.0)


def margin_for(fs: float) -> float:
    return max(MARGIN, fs * 0.4)


def estimate_size(op_type: str, payload: dict[str, Any]) -> tuple[float, float]:
    fs = payload.get("font_size") or FONT_SIZE
    if op_type == "write_text":
        wrap = payload.get("wrap_chars") or 0  # legacy ops carry none: no wrapping
        lines = str(payload.get("text", "")).split("\n")
        visual = sum(max(1, math.ceil(len(line) / wrap)) if wrap else 1 for line in lines)
        cols = max(len(line) for line in lines)
        return (max(1, min(cols, wrap) if wrap else cols) * 0.6 * fs, visual * 1.25 * fs)
    return (DIAGRAM_SIZE[0] * fs / FONT_SIZE, DIAGRAM_SIZE[1] * fs / FONT_SIZE)


def rotated_box(box: Box, angle: float) -> Box:
    """Axis-aligned box around `box` turned by `angle` radians about its centre.

    Excalidraw rotates an element about the centre of its unrotated box, so an upright-turned bar
    reaches far beyond that box; placement must keep clear of the turned shape.
    """
    if not angle:
        return box
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    c, s = abs(math.cos(angle)), abs(math.sin(angle))
    w = box["width"] * c + box["height"] * s
    h = box["width"] * s + box["height"] * c
    return {"x": cx - w / 2, "y": cy - h / 2, "width": w, "height": h}


def overlaps(a: Box, b: Box, margin: float = MARGIN) -> bool:
    return (
        a["x"] < b["x"] + b["width"] + margin
        and b["x"] < a["x"] + a["width"] + margin
        and a["y"] < b["y"] + b["height"] + margin
        and b["y"] < a["y"] + a["height"] + margin
    )


def place(
    occupied: list[Box],
    size: tuple[float, float],
    anchor: Box | None = None,
    fs: float = FONT_SIZE,
    clear: float = 0.0,
    recent: Box | None = None,
) -> dict[str, float]:
    """Top-left for a box of `size`. Order: right of anchor, below anchor, below / right of the
    most recent draft (column packing), then below everything. `clear` is the chunker proximity
    threshold: gap and margin never drop under it, so an accepted draft is not chunked into
    its neighbour."""
    w, h = size
    gap = max(gap_for(fs), clear * 1.05)  # 5% so "exactly the threshold" still counts as apart
    margin = max(margin_for(fs), clear * 1.05)

    def free(x: float, y: float) -> bool:
        box: Box = {"x": x, "y": y, "width": w, "height": h}
        return not any(overlaps(box, o, margin) for o in occupied)

    candidates: list[tuple[float, float]] = []
    if anchor is not None:
        candidates += [
            (anchor["x"] + anchor["width"] + gap, anchor["y"]),
            (anchor["x"], anchor["y"] + anchor["height"] + gap),
        ]
    if recent is not None:
        candidates += [
            (recent["x"], recent["y"] + recent["height"] + gap),
            (recent["x"] + recent["width"] + gap, recent["y"]),
        ]
    for x, y in candidates:
        if free(x, y):
            return {"x": x, "y": y}
    if not occupied:
        return {"x": 0, "y": 0}
    return {
        "x": min(o["x"] for o in occupied),
        "y": max(o["y"] + o["height"] for o in occupied) + gap,
    }
