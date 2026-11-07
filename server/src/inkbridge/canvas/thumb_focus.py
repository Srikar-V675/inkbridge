"""Which part of the canvas a home thumbnail shows (INK-179, decision 0084). Pure: boxes in, box out."""

import math

Box = tuple[float, float, float, float]  # x0, y0, x1, y1

TINY_SHARE = 0.05  # a centre chunk shorter than this share of the extent is grown
GROW_CAP_SHARE = 0.25  # ... but never past this share
MIN_SIDE = 20.0  # canvas units: floor for "one chunk-width"
FLOOD_MAX = 60  # no chunks yet: at most this many primitives around the centre
FLOOD_GAP_MIN = 30.0


def _median(v: list[float]) -> float:
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _centre(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _side(b: Box) -> float:
    return max(b[2] - b[0], b[3] - b[1])


def _union(a: Box, b: Box) -> Box:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _gap(a: Box, b: Box) -> float:
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0.0), max(a[1] - b[3], b[1] - a[3], 0.0))


def median_centre(boxes: list[Box]) -> tuple[float, float]:
    cs = [_centre(b) for b in boxes]
    return _median([c[0] for c in cs]), _median([c[1] for c in cs])


def _nearest(boxes: list[Box], at: tuple[float, float]) -> int:
    """Box whose centre is nearest `at`; ties: bigger area, then top-most, then left-most."""

    def key(i: int):
        b = boxes[i]
        cx, cy = _centre(b)
        return (
            round(math.hypot(cx - at[0], cy - at[1]), 6),
            -(b[2] - b[0]) * (b[3] - b[1]),
            b[1],
            b[0],
        )

    return min(range(len(boxes)), key=key)


def _grow(core: Box, others: list[Box], extent: Box) -> Box:
    reach = max(_side(core), MIN_SIDE)
    cap = max(GROW_CAP_SHARE * _side(extent), _side(core))
    cc = _centre(core)

    def order(b: Box):
        bc = _centre(b)
        return _gap(core, b), math.hypot(bc[0] - cc[0], bc[1] - cc[1]), b[1], b[0]

    near = sorted((b for b in others if _gap(core, b) <= reach), key=order)
    box = core
    for b in near:
        grown = _union(box, b)
        if _side(grown) <= cap:
            box = grown
    return box


def _flood(prims: list[Box], at: tuple[float, float]) -> Box:
    seed = _nearest(prims, at)
    gap = max(_side(prims[seed]), FLOOD_GAP_MIN)
    seen, queue, box = {seed}, [seed], prims[seed]
    while queue and len(seen) < FLOOD_MAX:
        i = queue.pop(0)
        for j in sorted(range(len(prims)), key=lambda j: (_gap(prims[i], prims[j]), j)):
            if j in seen or _gap(prims[i], prims[j]) > gap:
                continue
            seen.add(j)
            queue.append(j)
            box = _union(box, prims[j])
            if len(seen) >= FLOOD_MAX:
                break
    return box


def choose_focus(prims: list[Box], chunks: list[Box], extent: Box) -> Box | None:
    """The box a thumbnail shows, or None when there is no ink. `prims` are primitive bounds."""
    if not prims:
        return None
    at = median_centre(prims)
    if not chunks:
        return _flood(prims, at)
    i = _nearest(chunks, at)
    core = chunks[i]
    if _side(core) < TINY_SHARE * max(_side(extent), 1.0):
        return _grow(core, chunks[:i] + chunks[i + 1 :], extent)
    return core
