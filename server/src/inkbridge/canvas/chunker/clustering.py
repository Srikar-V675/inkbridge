"""Proximity clustering with a local scale and a size cap (INK-081)."""

import bisect
import math
import statistics
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from inkbridge.canvas.chunker.config import ChunkerConfig, clustering_elements
from inkbridge.canvas.hashes import bbox_of

# An element covering more cells than this moves to the next, coarser grid level.
_MAX_CELLS = 64
_LEVEL_FACTOR = 8


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    gx = max(a[0] - b[2], b[0] - a[2], 0.0)
    gy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(gx, gy)


def cluster(elements: list[dict[str, Any]], config: ChunkerConfig | None = None) -> list[list[str]]:
    """Proximity step only: chunks as sorted lists of element ids, ordered by their smallest id."""
    return _proximity(elements, config or ChunkerConfig())[0]


def proximity_threshold(
    elements: list[dict[str, Any]], config: ChunkerConfig | None = None
) -> float:
    """Distance under which the chunker joins two elements (k * median size); 0 on an empty page."""
    config = config or ChunkerConfig()
    clusters, median = _proximity(elements, config)
    return config.k * median if clusters else 0.0


def _box(e: dict[str, Any]) -> tuple[float, float, float, float]:
    b = bbox_of([e])
    return (b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"])


def _own_scale(boxes: Sequence[tuple[float, float, float, float]], config: ChunkerConfig) -> float:
    sizes = [max(b[2] - b[0], b[3] - b[1]) for b in boxes]
    return max(statistics.median(sizes), config.min_median)


def _cap(
    ids: list[str], boxes: Mapping[str, tuple[float, float, float, float]], config: ChunkerConfig
):
    """Cut a group wider or taller than max_extent * its own median at its largest gap, recursively."""
    xs = [boxes[i] for i in ids]
    limit = config.max_extent * _own_scale(xs, config)
    w = max(b[2] for b in xs) - min(b[0] for b in xs)
    h = max(b[3] for b in xs) - min(b[1] for b in xs)
    if len(ids) < 2 or (w <= limit and h <= limit):
        return [sorted(ids)]
    axis = 0 if w >= h else 1  # cut across the longer side
    order = sorted(ids, key=lambda i: (boxes[i][axis], i))
    best, cut, reach = -math.inf, 1, boxes[order[0]][axis + 2]
    for n, i in enumerate(order[1:], 1):  # gap between the running far edge and the next near edge
        gap = boxes[i][axis] - reach
        # equal gaps (evenly spaced strokes): cut nearest the middle, not off the first stroke
        if gap > best or (gap == best and abs(n - len(order) / 2) < abs(cut - len(order) / 2)):
            best, cut = gap, n
        reach = max(reach, boxes[i][axis + 2])
    return _cap(order[:cut], boxes, config) + _cap(order[cut:], boxes, config)


def _proximity(
    elements: list[dict[str, Any]],
    config: ChunkerConfig,
    exclude: Collection[str] = (),
    scale: float | None = None,
) -> tuple[list[list[str]], float]:
    """Proximity clusters and the median element size they were measured with.

    Ids in `exclude` (pinned ink, INK-059) take no part in the clusters but still count in the
    median, so pinning a group does not change how the rest of the page clusters.
    """
    every = sorted(clustering_elements(elements), key=lambda e: str(e["id"]))
    if not every:
        return [], config.min_median
    sizes = [max(b[2] - b[0], b[3] - b[1]) for b in map(_box, every)]
    median = max(statistics.median(sizes), config.min_median) if scale is None else scale
    threshold = config.k * median
    live = [e for e in every if str(e["id"]) not in exclude] if exclude else every
    if not live:
        return [], median
    boxes = [_box(e) for e in live]

    index = {str(e["id"]): i for i, e in enumerate(live)}
    uf = _UnionFind(len(live))

    # Bound text joins its container directly, whatever the distance.
    for i, e in enumerate(live):
        container_id = e.get("containerId")
        container = index.get(str(container_id)) if container_id is not None else None
        if container is not None:
            uf.union(i, container)

    # Multi-level grid: an element is indexed at the finest level where it covers few cells, so
    # oversize elements never fall back to comparing against everything. Level-0 cells are half
    # the threshold wide, so any two boxes touching one cell are at most threshold / sqrt(2)
    # apart: each level-0 cell is merged up front and then skipped as a whole once it is in the
    # same group, which keeps dense ink (hatching, overwritten strokes) near-linear.
    base = threshold / 2
    levels: list[dict[tuple[int, int], list[int]]] = [{}]

    def span(b: tuple[float, float, float, float], pad: float, cell: float):
        return (
            range(math.floor((b[0] - pad) / cell), math.floor((b[2] + pad) / cell) + 1),
            range(math.floor((b[1] - pad) / cell), math.floor((b[3] + pad) / cell) + 1),
        )

    # Elements with identical boxes (overwritten strokes, stacked shapes) touch, so they merge
    # here and only the first of them goes into the grid.
    first_with_box: dict[tuple[float, float, float, float], int] = {}
    indexed = []
    for i, b in enumerate(boxes):
        first = first_with_box.setdefault(b, i)
        if first == i:
            indexed.append(i)
        else:
            uf.union(first, i)

    for i in indexed:
        b = boxes[i]
        level = 0
        while True:
            xs, ys = span(b, 0.0, base * _LEVEL_FACTOR**level)
            if len(xs) * len(ys) <= _MAX_CELLS:
                break
            level += 1
        while len(levels) <= level:
            levels.append({})
        for cx in xs:
            for cy in ys:
                levels[level].setdefault((cx, cy), []).append(i)

    for members in levels[0].values():
        for j in members[1:]:
            uf.union(members[0], j)
    # Per level, cells known to hold a single group (one member stands for all). Groups only
    # grow, so a cell stays single-group once it is; coarser cells are checked lazily.
    single: list[dict[tuple[int, int], int]] = [{key: m[0] for key, m in levels[0].items()}]
    single += [{} for _ in levels[1:]]

    for i in indexed:
        b = boxes[i]
        root = uf.find(i)
        for level, cells in enumerate(levels):
            xs, ys = span(b, threshold, base * _LEVEL_FACTOR**level)
            if len(xs) * len(ys) > len(cells):  # cheaper to scan the occupied cells
                keys = [
                    key
                    for key in cells
                    if xs.start <= key[0] < xs.stop and ys.start <= key[1] < ys.stop
                ]
            else:
                keys = [(cx, cy) for cx in xs for cy in ys if (cx, cy) in cells]
            for key in keys:
                rep = single[level].get(key)
                if rep is not None and uf.find(rep) == root:
                    continue  # the whole cell is already in this group
                members = cells[key]
                # Members are stored in index order; pairs are tested once, from the lower index.
                for j in members[bisect.bisect_right(members, i) :]:
                    if uf.find(j) != root and _gap(b, boxes[j]) < threshold:
                        uf.union(i, j)
                        root = uf.find(i)
                        if rep is not None:
                            break  # one member joined, so the whole cell did
                if rep is None and all(uf.find(m) == root for m in members):
                    single[level][key] = members[0]

    found: dict[int, list[str]] = {}
    for i, e in enumerate(live):
        found.setdefault(uf.find(i), []).append(str(e["id"]))

    # Local scale (INK-081): a group of small writing that the page-wide median glued together
    # (zoomed-out and zoomed-in text on one canvas) is re-clustered with its own median.
    by_id = {str(e["id"]): e for e in live}
    box_of = {str(e["id"]): b for e, b in zip(live, boxes)}
    groups: list[list[str]] = []
    pending = list(found.values())
    while pending:
        g = pending.pop()
        own = _own_scale([box_of[i] for i in g], config)
        if len(g) > 1 and own < 0.5 * median:
            sub = _proximity([by_id[i] for i in g], config, scale=own)[0]
            if len(sub) > 1:
                pending += sub
                continue
        groups += _cap(g, box_of, config)

    # The cap may cut a label from its container: bound text goes back to its container's group.
    home = {i: gi for gi, g in enumerate(groups) for i in g}
    for i, e in by_id.items():
        c = e.get("containerId")
        if c is not None and str(c) in home and home[str(c)] != home[i]:
            groups[home[i]].remove(i)
            groups[home[str(c)]].append(i)
            home[i] = home[str(c)]
    return sorted((sorted(g) for g in groups if g), key=lambda g: g[0]), median
