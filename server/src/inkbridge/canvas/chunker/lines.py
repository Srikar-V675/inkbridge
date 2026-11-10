"""Chunker v2 proximity: line-aware gaps, ink-confirmed for long strokes (INK-122, decision 0081).

Same output as `_proximity`, but two elements join by the rules of handwriting: on one line they
join within k * T, on adjacent lines only when their boxes overlap in x and the gap is under
next_line * T. A stroke longer than long_stroke * T joins by its ink, not its bounding box, so an
arc round a word does not swallow it. A container loop unions what it holds.
"""

import bisect
import itertools
import math
import statistics
from collections.abc import Collection
from typing import Any

from inkbridge.canvas.chunker.clustering import (
    _MAX_CELLS,
    _box,
    _cap,
    _own_scale,
    _UnionFind,
)
from inkbridge.canvas.chunker.config import ChunkerConfig, clustering_elements, stroke_connector_ids
from inkbridge.canvas.strokes import UNDERLINE_REACH, StrokeKinds, _inside_polygon

Box = tuple[float, float, float, float]
_MAX_SAMPLES = 256


def _threshold(a: Box, b: Box, t: float, cfg: ChunkerConfig, underline: bool) -> float | None:
    gx = max(a[0] - b[2], b[0] - a[2], 0.0)
    gy = max(a[1] - b[3], b[1] - a[3], 0.0)
    overlap = min(a[3], b[3]) - max(a[1], b[1])  # vertical overlap
    smaller = min(a[3] - a[1], b[3] - b[1])
    if overlap > 0 and overlap >= 0.5 * smaller:  # same line
        return cfg.k * t if gx < cfg.k * t else None
    reach = max(cfg.next_line, UNDERLINE_REACH if underline else 0.0) * t
    if gy < reach and gx < cfg.k * t:  # next line: above or beside, diagonal neighbours too
        return reach
    return None


def _samples(e: dict[str, Any], t: float) -> list[tuple[float, float]]:
    """Absolute points along a stroke, every t / 2 px of path, at most _MAX_SAMPLES."""
    x, y = e.get("x", 0), e.get("y", 0)
    pts = [(x + p[0], y + p[1]) for p in e.get("points") or []]
    if len(pts) < 2:
        return pts
    total = sum(math.dist(a, b) for a, b in itertools.pairwise(pts))
    step = max(t / 2, 1.0, total / (_MAX_SAMPLES - 1))
    out = [pts[0]]
    run = 0.0
    for a, b in itertools.pairwise(pts):
        run += math.dist(a, b)
        if run >= step:
            out.append(b)
            run = 0.0
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _point_box(p: tuple[float, float], b: Box) -> float:
    return math.hypot(max(b[0] - p[0], 0.0, p[0] - b[2]), max(b[1] - p[1], 0.0, p[1] - b[3]))


def _ink_below(
    sa: list[tuple[float, float]] | None,
    box_a: Box,
    sb: list[tuple[float, float]] | None,
    box_b: Box,
    limit: float,
) -> bool:
    """True if the ink of a and b comes within `limit`; a long stroke is its samples, else its box."""
    if sa is not None and sb is not None:
        return any(math.dist(p, q) < limit for p in sa for q in sb)
    if sa is not None:
        return any(_point_box(p, box_b) < limit for p in sa)
    if sb is not None:
        return any(_point_box(q, box_a) < limit for q in sb)
    return True  # two short elements: the box test already decided


_SHAPES = {"rectangle", "diamond", "ellipse"}


def _apart_shapes(a_el: dict, b_el: dict, a: Box, b: Box) -> bool:
    """Two drawn shapes that do not overlap: near is not the same idea. Arrows decide (0106)."""
    return (
        a_el.get("type") in _SHAPES
        and b_el.get("type") in _SHAPES
        and not (a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3])
    )


def cluster_lines(
    elements: list[dict[str, Any]],
    config: ChunkerConfig,
    kinds: StrokeKinds,
    exclude: Collection[str] = (),
    scale: float | None = None,
) -> tuple[list[list[str]], float]:
    """v2 proximity: line-aware gaps, ink-confirmed for long strokes. Same return as `_proximity`."""
    skip = stroke_connector_ids(kinds)
    every = sorted(
        (e for e in clustering_elements(elements) if str(e["id"]) not in skip),
        key=lambda e: str(e["id"]),
    )
    if not every:
        return [], config.min_median
    if scale is not None:
        t = scale
    elif kinds.scale > 0:
        t = max(kinds.scale, config.min_median)
    else:
        sizes = [max(b[2] - b[0], b[3] - b[1]) for b in map(_box, every)]
        t = max(statistics.median(sizes), config.min_median)
    live = [e for e in every if str(e["id"]) not in exclude] if exclude else every
    if not live:
        return [], t
    boxes = [_box(e) for e in live]
    ids = [str(e["id"]) for e in live]
    index = {eid: i for i, eid in enumerate(ids)}
    uf = _UnionFind(len(live))
    kind = [kinds.kinds.get(eid) for eid in ids]

    long_limit = config.long_stroke * t
    is_long = [
        e.get("type") == "freedraw" and max(b[2] - b[0], b[3] - b[1]) > long_limit
        for e, b in zip(live, boxes, strict=True)
    ]
    cache: dict[int, list[tuple[float, float]]] = {}

    def samples(i: int) -> list[tuple[float, float]] | None:
        if not is_long[i]:
            return None
        if i not in cache:
            cache[i] = _samples(live[i], t)
        return cache[i]

    def joins(i: int, j: int) -> bool:
        a, b = boxes[i], boxes[j]
        if kind[i] == "scribble" or kind[j] == "scribble":  # a scribble joins what it overlaps
            return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
        if _apart_shapes(live[i], live[j], a, b):
            return False
        limit = _threshold(a, b, t, config, "underline" in (kind[i], kind[j]))
        if limit is None:
            return False
        if is_long[i] or is_long[j]:
            return _ink_below(samples(i), a, samples(j), b, limit)
        return True

    # Bound text joins its container directly, whatever the distance.
    for i, e in enumerate(live):
        container_id = e.get("containerId")
        container = index.get(str(container_id)) if container_id is not None else None
        if container is not None:
            uf.union(i, container)

    # A container loop is one node with whatever it holds, whatever the line gaps are.
    for i, e in enumerate(live):
        if kind[i] != "container":
            continue
        poly = [(e.get("x", 0) + p[0], e.get("y", 0) + p[1]) for p in e.get("points") or []]
        b = boxes[i]
        for j, o in enumerate(boxes):
            cx, cy = (o[0] + o[2]) / 2, (o[1] + o[3]) / 2
            if (
                j != i
                and b[0] <= cx <= b[2]
                and b[1] <= cy <= b[3]
                and _inside_polygon((cx, cy), poly)
            ):
                uf.union(i, j)

    # One grid level, cells k * T wide. Short elements with identical boxes touch, so they merge
    # here and only the first goes into the grid. Elements over _MAX_CELLS cells are tested
    # against everything.
    cell = config.k * t

    def span(b: Box, pad: float):
        return (
            range(math.floor((b[0] - pad) / cell), math.floor((b[2] + pad) / cell) + 1),
            range(math.floor((b[1] - pad) / cell), math.floor((b[3] + pad) / cell) + 1),
        )

    first_with_box: dict[Box, int] = {}
    indexed: list[int] = []
    for i, b in enumerate(boxes):
        if is_long[i] or kind[i] == "scribble":
            indexed.append(i)
            continue
        first = first_with_box.setdefault(b, i)
        if first == i:
            indexed.append(i)
        else:
            uf.union(first, i)

    cells: dict[tuple[int, int], list[int]] = {}
    large: list[int] = []
    for i in indexed:
        xs, ys = span(boxes[i], 0.0)
        if len(xs) * len(ys) > _MAX_CELLS:
            large.append(i)
            continue
        for cx in xs:
            for cy in ys:
                cells.setdefault((cx, cy), []).append(i)

    # Cells known to hold a single group (one member stands for all). Groups only grow, so a cell
    # stays single-group once it is; a pair is only tested when its roots differ.
    single: dict[tuple[int, int], int] = {}
    large_set = set(large)
    for i in indexed:
        b = boxes[i]
        root = uf.find(i)
        if i in large_set:
            for j in range(len(live)):
                if j != i and uf.find(j) != root and joins(i, j):
                    uf.union(i, j)
                    root = uf.find(i)
            continue
        for j in large:
            if uf.find(j) != root and joins(i, j):
                uf.union(i, j)
                root = uf.find(i)
        xs, ys = span(b, cell)
        if len(xs) * len(ys) > len(cells):
            keys = [k for k in cells if xs.start <= k[0] < xs.stop and ys.start <= k[1] < ys.stop]
        else:
            keys = [(cx, cy) for cx in xs for cy in ys if (cx, cy) in cells]
        for key in keys:
            rep = single.get(key)
            if rep is not None and uf.find(rep) == root:
                continue  # the whole cell is already in this group
            members = cells[key]
            for j in members[bisect.bisect_right(members, i) :]:
                if uf.find(j) != root and joins(i, j):
                    uf.union(i, j)
                    root = uf.find(i)
                    if rep is not None:
                        break  # one member joined, so the whole single-group cell did
            if rep is None and all(uf.find(m) == root for m in members):
                single[key] = members[0]

    found: dict[int, list[str]] = {}
    for i, eid in enumerate(ids):
        found.setdefault(uf.find(i), []).append(eid)

    # Local scale (INK-081), kept from v1: small writing the page scale glued is re-clustered
    # with its own median.
    by_id = {eid: e for eid, e in zip(ids, live, strict=True)}
    box_of = dict(zip(ids, boxes, strict=True))
    groups: list[list[str]] = []
    pending = list(found.values())
    while pending:
        g = pending.pop()
        own = _own_scale([box_of[i] for i in g], config)
        if len(g) > 1 and own < 0.5 * t:
            sub = cluster_lines([by_id[i] for i in g], config, kinds, scale=own)[0]
            if len(sub) > 1:
                pending += sub
                continue
        groups += _cap(g, box_of, config, split_overlapping=False)

    # The cap may cut a label from its container: bound text goes back to its container's group.
    home = {i: gi for gi, g in enumerate(groups) for i in g}
    for i, e in by_id.items():
        c = e.get("containerId")
        if c is not None and str(c) in home and home[str(c)] != home[i]:
            groups[home[i]].remove(i)
            groups[home[str(c)]].append(i)
            home[i] = home[str(c)]
    return sorted((sorted(g) for g in groups if g), key=lambda g: g[0]), t
