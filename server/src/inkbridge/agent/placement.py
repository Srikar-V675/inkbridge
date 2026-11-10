"""Where an agent op lands on the canvas. Pure: no I/O, no SQLite.

The server decides the position from the stored scene so it is deterministic and testable; the
browser only draws at it. Sizes are estimates (the browser lays text and Mermaid out), so the
"below everything" fallback is the one position that can never overlap whatever the true size.
"""

import itertools
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
INK_TO_FONT = 1.0  # fallback text size per px of median stroke height when there is no line pitch
LINE_FACTOR = 0.75  # font per px of line pitch (ticket says ~0.8; 0.75 keeps the fixture inside 0.7-1.3 x letter height)
MIN_SAMPLES = 3
WRAP_MAX, WRAP_MIN = 34, 8  # server-set wrap width in characters
RINGS = (1.0, 1.5, 2.5, 4.0, 6.0)  # candidate distances from the anchor, in gaps
# 8 directions as (dx, dy, direction_penalty): E, SE, S, SW, W, NW, N, NE
DIRS = (
    (1, 0, 0.0),
    (1, 1, 0.1),
    (0, 1, 0.2),
    (-1, 1, 0.4),
    (-1, 0, 0.6),
    (-1, -1, 0.7),
    (0, -1, 0.8),
    (1, -1, 0.4),
)
W_DIST, W_VIEW, W_CROSS, W_DIR, W_ALIGN = 1.0, 3.0, 2.0, 0.5, 1.0
SIZE_HINTS = {"small": 0.75, "normal": 1.0, "large": 1.5}
# Mermaid is laid out in the browser; reserve a generous box for a typical small flowchart.
DIAGRAM_SIZE = (600.0, 400.0)


def line_pitch(rows: list[tuple[float, float]]) -> float | None:
    """rows = (centre_y, height) per stroke. Strokes whose centres are within half the median
    height of the line's first stroke share a line; pitch = median distance between line centres."""
    rows = sorted((cy, h) for cy, h in rows if h > 0)
    if len(rows) < MIN_SAMPLES:
        return None
    tol = 0.5 * statistics.median(h for _, h in rows)
    lines: list[list[float]] = []
    for cy, _ in rows:
        if lines and cy - lines[-1][0] <= tol:
            lines[-1].append(cy)
        else:
            lines.append([cy])
    if len(lines) < 2:
        return None
    centres = [statistics.fmean(ln) for ln in lines]
    return statistics.median(b - a for a, b in itertools.pairwise(centres))


def font_size_for(
    stroke_heights: list[float], hint: str | None = None, pitch: float | None = None
) -> int:
    """Font size that reads beside this handwriting: LINE_FACTOR x line pitch, else stroke height."""
    heights = [h for h in stroke_heights if h > 0]
    if pitch and pitch > 0:
        base = pitch * LINE_FACTOR
    elif len(heights) >= MIN_SAMPLES:
        base = statistics.median(heights) * INK_TO_FONT
    else:
        base = DEFAULT_FONT
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


def wrap_for(fs: float, view: dict | None) -> int:
    """Characters per line: about the view width in font sizes, within WRAP_MIN..WRAP_MAX."""
    if not view or not view.get("zoom") or view["zoom"] <= 0:
        return WRAP_MAX
    return max(WRAP_MIN, min(WRAP_MAX, int(view["width"] / view["zoom"] / fs)))


def view_rect(view: dict | None) -> Box | None:
    """Scene rect of an attention view (x, y scene origin; width, height in screen px)."""
    if not view or not view.get("zoom") or view["zoom"] <= 0:
        return None
    z = view["zoom"]
    return {
        "x": view["x"],
        "y": view["y"],
        "width": view["width"] / z,
        "height": view["height"] / z,
    }


def connectors_of(
    elements: list[dict], cap: int = 500
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Segments of live arrows/lines in scene coordinates, first `cap`."""
    out: list = []
    for e in elements:
        if e.get("type") not in ("arrow", "line") or e.get("isDeleted"):
            continue
        pts = [(e.get("x", 0) + p[0], e.get("y", 0) + p[1]) for p in e.get("points") or []]
        out += itertools.pairwise(pts)
        if len(out) >= cap:
            break
    return out[:cap]


def _crosses(box: Box, seg) -> bool:
    """Liang-Barsky: does the segment touch the box?"""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, x0 - box["x"]),
        (dx, box["x"] + box["width"] - x0),
        (-dy, y0 - box["y"]),
        (dy, box["y"] + box["height"] - y0),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _dist(a: Box, b: Box) -> float:
    dx = max(0.0, a["x"] - b["x"] - b["width"], b["x"] - a["x"] - a["width"])
    dy = max(0.0, a["y"] - b["y"] - b["height"], b["y"] - a["y"] - a["height"])
    return math.hypot(dx, dy)


def _inside_frac(box: Box, view: Box) -> float:
    iw = min(box["x"] + box["width"], view["x"] + view["width"]) - max(box["x"], view["x"])
    ih = min(box["y"] + box["height"], view["y"] + view["height"]) - max(box["y"], view["y"])
    area = box["width"] * box["height"]
    return max(0.0, iw) * max(0.0, ih) / area if area > 0 else 1.0


def place(
    occupied: list[Box],
    size: tuple[float, float],
    anchor: Box | None = None,
    fs: float = FONT_SIZE,
    recent: Box | None = None,
    view: Box | None = None,
    connectors=(),
) -> dict[str, float]:
    """Top-left for a box of `size`: the best-scored free candidate (rings of slots around the
    anchor, a grid over the view, the column under `recent`); below everything only if none is free.
    `view` is a scene rect and only ranks free spots."""
    w, h = size
    gap, margin = gap_for(fs), margin_for(fs)
    if not occupied:
        return {"x": 0, "y": 0}
    cands: dict[tuple[float, float], float] = {}  # (x, y) -> direction penalty

    def add(x: float, y: float, pen: float) -> None:
        cands[(x, y)] = min(pen, cands.get((x, y), pen))

    if anchor is not None:
        for k in RINGS:
            d = gap * k
            for dx, dy, pen in DIRS:
                x = (
                    anchor["x"] + anchor["width"] + d
                    if dx > 0
                    else anchor["x"] - d - w
                    if dx < 0
                    else anchor["x"]
                )
                y = (
                    anchor["y"] + anchor["height"] + d
                    if dy > 0
                    else anchor["y"] - d - h
                    if dy < 0
                    else anchor["y"]
                )
                add(x, y, pen)
        for o in occupied:
            if 0 < _dist(o, anchor) < 6 * gap:  # 0 = part of the anchor itself
                add(o["x"] + o["width"] + gap, o["y"], 0.2)
                add(o["x"], o["y"] + o["height"] + gap, 0.2)
    elif view is not None:
        step = max(gap, w / 2, view["width"] / 8, view["height"] / 8)  # at most 9 x 9 cells
        for i in range(int(view["width"] / step) + 1):
            for j in range(int(view["height"] / step) + 1):
                add(view["x"] + i * step, view["y"] + j * step, 0.0)
    else:
        add(min(o["x"] for o in occupied), max(o["y"] + o["height"] for o in occupied) + gap, 0.0)
    if recent is not None:
        add(recent["x"], recent["y"] + recent["height"] + gap, 0.0)
        add(recent["x"] + recent["width"] + gap, recent["y"], 0.2)

    # Only boxes near some candidate can overlap it; the fallback below still uses all of them.
    x0, y0 = min(x for x, _ in cands) - margin, min(y for _, y in cands) - margin
    x1, y1 = max(x for x, _ in cands) + w + margin, max(y for _, y in cands) + h + margin
    near = [
        o
        for o in occupied
        if o["x"] < x1 and o["x"] + o["width"] > x0 and o["y"] < y1 and o["y"] + o["height"] > y0
    ]
    best = None
    for (x, y), pen in cands.items():
        box: Box = {"x": x, "y": y, "width": w, "height": h}
        if any(overlaps(box, o, margin) for o in near):
            continue
        ref = anchor or recent
        score = (
            W_DIST * (_dist(box, ref) / fs if ref else 0.0)
            + W_VIEW * (1 - _inside_frac(box, view) if view else 0.0)
            + W_CROSS * any(_crosses(box, c) for c in connectors)
            + W_DIR * pen
            - W_ALIGN * bool(recent and x == recent["x"])
        )
        key = (round(score, 9), x, y)
        if best is None or key < best:
            best = key
    if best is not None:
        return {"x": best[1], "y": best[2]}
    return {
        "x": min(o["x"] for o in occupied),
        "y": max(o["y"] + o["height"] for o in occupied) + gap,
    }
