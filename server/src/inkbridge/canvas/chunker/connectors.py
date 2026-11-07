"""Connector ends for chunker v2: which chunk box is nearest a stroke end (INK-122)."""

import math
from collections.abc import Sequence
from typing import Any

from inkbridge.canvas.chunker.clustering import _MAX_CELLS
from inkbridge.canvas.chunker.scene import _box_distance

Point = tuple[float, float]


class EndIndex:
    """Nearest chunk box within `reach` of a point: a uniform grid of reach-wide cells.

    A point needs the 3 x 3 cells around it. Boxes too large for the grid are always candidates.
    Inside nested boxes the smallest wins, then the first in index order.
    """

    def __init__(self, boxes: Sequence[dict[str, float]], reach: float):
        self.boxes = boxes
        self.reach = reach
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.large: list[int] = []
        for gi, b in enumerate(boxes):
            xs = range(math.floor(b["x"] / reach), math.floor((b["x"] + b["width"]) / reach) + 1)
            ys = range(math.floor(b["y"] / reach), math.floor((b["y"] + b["height"]) / reach) + 1)
            if len(xs) * len(ys) > _MAX_CELLS:
                self.large.append(gi)
                continue
            for cx in xs:
                for cy in ys:
                    self.cells.setdefault((cx, cy), []).append(gi)

    def nearest(self, point: Point) -> tuple[int, float] | None:
        """(box index, distance) of the closest box within reach, else None."""
        px, py = math.floor(point[0] / self.reach), math.floor(point[1] / self.reach)
        candidates = set(self.large)
        for cx in range(px - 1, px + 2):
            for cy in range(py - 1, py + 2):
                candidates.update(self.cells.get((cx, cy), ()))
        scored = [
            (
                _box_distance(point, self.boxes[gi]),
                self.boxes[gi]["width"] * self.boxes[gi]["height"],
                gi,
            )
            for gi in candidates
        ]
        best = min(scored, default=None)
        if best is None or best[0] > self.reach:
            return None
        return best[2], best[0]


def end_points(c: dict[str, Any]) -> tuple[Point, Point] | None:
    """Absolute first and last point of a connector, None when it has no drawn path."""
    points = c.get("points") or []
    if len(points) < 2:
        return None
    x, y = c.get("x", 0), c.get("y", 0)
    out = ((x + points[0][0], y + points[0][1]), (x + points[-1][0], y + points[-1][1]))
    return out if all(map(math.isfinite, (*out[0], *out[1]))) else None
