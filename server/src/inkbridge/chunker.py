"""Pure chunker: group scene elements into chunks by proximity. No I/O, no SQLite.

Steps 1-3 and 6 of the pipeline in the technical reference (section 5). Arrow merge/link rules
and id matching live elsewhere (INK-032, INK-031); their constants sit in ChunkerConfig so one
object tunes the whole pipeline.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Any

from inkbridge.regions import bbox_of

# Elements that join chunks through other rules, not by proximity.
_CONNECTORS = {"arrow", "line"}
_SHAPES = {"rectangle", "ellipse", "diamond", "arrow", "line", "frame"}
# An element covering more cells than this moves to the next, coarser grid level.
_MAX_CELLS = 64
_LEVEL_FACTOR = 8


@dataclass(frozen=True)
class ChunkerConfig:
    k: float = 1.5  # merge when gap < k * median element size
    arrow_merge: float = 6.0  # arrows shorter than this * median merge their chunks (INK-032)
    link_reach: float = 3.0  # free arrow ends link to chunks within this * median (INK-032)
    min_median: float = 4.0  # floor for the median size, in px


def is_draft(element: dict[str, Any]) -> bool:
    return bool((element.get("customData") or {}).get("draft"))


def clustering_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live elements that cluster by proximity: no deleted, no drafts, no arrows or lines."""
    return [
        e
        for e in elements
        if not e.get("isDeleted") and not is_draft(e) and e.get("type") not in _CONNECTORS
    ]


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
    """Return chunks as sorted lists of element ids, ordered by their smallest id."""
    config = config or ChunkerConfig()
    live = sorted(clustering_elements(elements), key=lambda e: str(e["id"]))
    if not live:
        return []
    boxes = []
    for e in live:
        b = bbox_of([e])
        boxes.append((b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]))
    sizes = [max(b[2] - b[0], b[3] - b[1]) for b in boxes]
    median = max(statistics.median(sizes), config.min_median)
    threshold = config.k * median

    index = {str(e["id"]): i for i, e in enumerate(live)}
    uf = _UnionFind(len(live))

    # Bound text joins its container directly, whatever the distance.
    for i, e in enumerate(live):
        container = index.get(str(e.get("containerId")))
        if container is not None:
            uf.union(i, container)

    # Multi-level grid: an element is indexed at the finest level where it covers few cells, so
    # oversize elements never fall back to comparing against everything.
    levels: list[dict[tuple[int, int], list[int]]] = []

    def span(b: tuple[float, float, float, float], pad: float, cell: float):
        return (
            range(math.floor((b[0] - pad) / cell), math.floor((b[2] + pad) / cell) + 1),
            range(math.floor((b[1] - pad) / cell), math.floor((b[3] + pad) / cell) + 1),
        )

    for i, b in enumerate(boxes):
        level = 0
        while True:
            xs, ys = span(b, 0.0, threshold * _LEVEL_FACTOR**level)
            if len(xs) * len(ys) <= _MAX_CELLS:
                break
            level += 1
        while len(levels) <= level:
            levels.append({})
        for cx in xs:
            for cy in ys:
                levels[level].setdefault((cx, cy), []).append(i)

    for i, b in enumerate(boxes):
        candidates: set[int] = set()
        for level, cells in enumerate(levels):
            xs, ys = span(b, threshold, threshold * _LEVEL_FACTOR**level)
            if len(xs) * len(ys) > len(cells):  # cheaper to scan the occupied cells
                for (cx, cy), members in cells.items():
                    if xs.start <= cx < xs.stop and ys.start <= cy < ys.stop:
                        candidates.update(members)
            else:
                for cx in xs:
                    for cy in ys:
                        candidates.update(cells.get((cx, cy), ()))
        for j in candidates:
            if j > i and uf.find(i) != uf.find(j) and _gap(b, boxes[j]) < threshold:
                uf.union(i, j)

    groups: dict[int, list[str]] = {}
    for i, e in enumerate(live):
        groups.setdefault(uf.find(i), []).append(str(e["id"]))
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


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
    live = [e for e in elements if not e.get("isDeleted")]
    shapes = sum(1 for e in live if e.get("type") in _SHAPES)
    writing = sum(1 for e in live if e.get("type") in {"freedraw", "text"})
    if shapes == 0:
        return "handwriting"
    if writing == 0:
        return "diagram"
    return "mixed"
