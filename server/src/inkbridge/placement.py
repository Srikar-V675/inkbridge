"""Where an agent op lands on the canvas. Pure: no I/O, no SQLite.

The server decides the position from the stored scene so it is deterministic and testable; the
browser only draws at it. Sizes are estimates (the browser lays text and Mermaid out), so the
"below everything" fallback is the one position that can never overlap whatever the true size.
"""

import math
from typing import Any, TypedDict


class Box(TypedDict):
    x: float
    y: float
    width: float
    height: float


GAP = 40  # space left between an op and the ink it is placed beside
MARGIN = 16  # boxes closer than this count as overlapping

# Excalidraw's default text is 20 px Virgil; about 0.6 em per character and 1.25 em per line.
FONT_SIZE = 20
CHAR_WIDTH = 0.6 * FONT_SIZE
LINE_HEIGHT = 1.25 * FONT_SIZE
# Mermaid is laid out in the browser; reserve a generous box for a typical small flowchart.
DIAGRAM_SIZE = (600.0, 400.0)


def estimate_size(op_type: str, payload: dict[str, Any]) -> tuple[float, float]:
    if op_type == "write_text":
        lines = str(payload.get("text", "")).split("\n")
        return (max(1, max(len(line) for line in lines)) * CHAR_WIDTH, len(lines) * LINE_HEIGHT)
    return DIAGRAM_SIZE


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
    occupied: list[Box], size: tuple[float, float], anchor: Box | None = None
) -> dict[str, float]:
    """Top-left corner for a box of `size`: right of the anchor, below it, or below everything."""
    w, h = size

    def free(x: float, y: float) -> bool:
        box: Box = {"x": x, "y": y, "width": w, "height": h}
        return not any(overlaps(box, o) for o in occupied)

    if anchor is not None:
        for x, y in (
            (anchor["x"] + anchor["width"] + GAP, anchor["y"]),
            (anchor["x"], anchor["y"] + anchor["height"] + GAP),
        ):
            if free(x, y):
                return {"x": x, "y": y}
    if not occupied:
        return {"x": 0, "y": 0}
    return {
        "x": min(o["x"] for o in occupied),
        "y": max(o["y"] + o["height"] for o in occupied) + GAP,
    }
