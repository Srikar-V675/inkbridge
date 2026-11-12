"""Cut chunks too big to read along their widest empty gap (INK-209, decision 0124).

A page of separate islands joined only by long arrows or a chain of short ones can end up as one
chunk thousands of units wide, which the reader refuses (`too_large`) and which no question or
export can use. After clustering (and before arrows merge chunks) a group over the caps is cut at
the widest gap between the boxes of its members, on the longer axis, and each part is cut again
until it fits or has no gap left. Members that overlap in both axes are never separated.
"""

from collections.abc import Sequence
from typing import Any

from inkbridge.canvas.hashes import bbox_of

MAX_SIDE = 3000.0  # units; the reader's own limit is 4096 (imaging.MAX_READ_UNITS)
MAX_ELEMENTS = 600  # imaging.MAX_CROP_ELEMENTS is 1500


def _extent(boxes: Sequence[dict[str, float]]) -> tuple[float, float]:
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return x1 - x0, y1 - y0


def _widest_gap(spans: list[tuple[float, float, int]]) -> tuple[float, float] | None:
    """(gap size, cut position) of the widest empty stretch between sorted (lo, hi, i) spans."""
    best: tuple[float, float] | None = None
    reach = None
    for lo, hi, _ in sorted(spans):
        if reach is not None and lo > reach:
            gap = lo - reach
            if best is None or gap > best[0]:
                best = (gap, (lo + reach) / 2)
        reach = hi if reach is None else max(reach, hi)
    return best


def _too_big(boxes: Sequence[dict[str, float]]) -> bool:
    return len(boxes) > MAX_ELEMENTS or max(_extent(boxes)) > MAX_SIDE


BRIDGE_FACTOR = 8.0  # an element this many times the median side bridges islands, not writes


def _core(boxes: Sequence[dict[str, float]]) -> list[int]:
    """Indices of the members that are not bridges: a frame or scribble spanning the islands."""
    sides = sorted(max(b["width"], b["height"]) for b in boxes)
    cutoff = max(sides[len(sides) // 2] * BRIDGE_FACTOR, MAX_SIDE / 3)
    return [i for i, b in enumerate(boxes) if max(b["width"], b["height"]) <= cutoff]


def _cut(ids: list[str], boxes: list[dict[str, float]]) -> list[list[str]]:
    if len(ids) < 2 or not _too_big(boxes):
        return [ids]
    w, h = _extent(boxes)
    options = []
    for axis, extent in (("x", w), ("y", h)):
        size = "width" if axis == "x" else "height"
        spans = [(b[axis], b[axis] + b[size], i) for i, b in enumerate(boxes)]
        gap = _widest_gap(spans)
        if gap is not None:
            options.append((extent, gap[0], gap[1], axis, size))
    if not options:
        return [ids]  # everything overlaps: one ink mass, not separable
    _, _, at, axis, size = max(options, key=lambda o: (o[0], o[1]))  # longer axis, then wider gap
    left = [i for i, b in enumerate(boxes) if b[axis] + b[size] / 2 < at]
    right = [i for i in range(len(ids)) if i not in set(left)]
    if not left or not right:
        return [ids]
    parts = []
    for side in (left, right):
        parts += _cut([ids[i] for i in side], [boxes[i] for i in side])
    return parts


def split_oversized(
    groups: Sequence[Sequence[str]], by_id: dict[str, dict[str, Any]]
) -> list[list[str]]:
    """The groups, with every one over the caps cut at its widest gaps. Order is kept.

    In a group over the caps, a bridge (a frame or scribble much bigger than the writing) would
    keep every gap closed, so bridges leave first and stand as chunks of their own.
    """
    out: list[list[str]] = []
    for g in groups:
        ids = [str(i) for i in g]
        boxes = [bbox_of([by_id[i]]) for i in ids]
        if not boxes or not _too_big(boxes):
            out.append(ids)
            continue
        core = _core(boxes)
        bridges = [i for i in range(len(ids)) if i not in set(core)]
        if len(core) < 2 or not bridges and not _too_big([boxes[i] for i in core]):
            out.append(ids)
            continue
        out += _cut([ids[i] for i in core], [boxes[i] for i in core])
        out += [[ids[i]] for i in bridges]
    return out
