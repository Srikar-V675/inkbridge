"""Pure chunker: group scene elements into chunks by proximity. No I/O, no SQLite.

Steps 1-3 and 6 of the pipeline in the technical reference (section 5). Step 5, stable ids,
is `match_chunks` (INK-031); arrow merge/link rules live in INK-032. Their constants sit in
ChunkerConfig so one object tunes the whole pipeline.
"""

import bisect
import math
import statistics
from collections.abc import Collection, Mapping, Sequence
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
    # A new cluster keeps an old chunk's id when their element-id Jaccard is above this. Small
    # chunks are fragile (2 elements gaining 3 is J = 0.4); INK-038 may switch to a 60%
    # containment test instead (docs/decisions/0011-chunk-identity.md).
    match_threshold: float = 0.5


def is_draft(element: dict[str, Any]) -> bool:
    return bool((element.get("customData") or {}).get("draft"))


def _takes_part(element: dict[str, Any]) -> bool:
    return (
        not element.get("isDeleted")
        and not is_draft(element)
        and element.get("type") not in _CONNECTORS
    )


def clustering_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live elements that cluster by proximity: no deleted, no drafts, no arrows or lines.

    Bound text follows its container: when the container is in the scene but does not take
    part (deleted, an unaccepted draft, or an arrow/line whose label goes with it in INK-032),
    the text is left out too, so a draft's label never becomes content. Text whose container
    id is missing from the scene clusters by proximity like any other element.
    """
    by_id = {str(e.get("id")): e for e in elements}
    out = []
    for e in elements:
        if not _takes_part(e):
            continue
        container_id = e.get("containerId")
        container = by_id.get(str(container_id)) if container_id is not None else None
        if container is not None and not _takes_part(container):
            continue
        out.append(e)
    return out


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
    live = [e for e in elements if not e.get("isDeleted") and not is_draft(e)]
    shapes = sum(1 for e in live if e.get("type") in _SHAPES)
    writing = sum(1 for e in live if e.get("type") in {"freedraw", "text"})
    if shapes == 0:
        return "handwriting"
    if writing == 0:
        return "diagram"
    return "mixed"


@dataclass(frozen=True)
class Matching:
    assigned: list[str | None]  # per new cluster: the old chunk id it keeps, or None for a new id
    successors: dict[str, int | None]  # newly orphaned old id -> cluster index (None: no overlap)


def match_chunks(
    old: Mapping[str, Sequence[str]],
    clusters: Sequence[Sequence[str]],
    tops: Sequence[float],
    active: Collection[str] | None = None,
    threshold: float = ChunkerConfig.match_threshold,
) -> Matching:
    """Give new clusters the ids of old chunks by element-id Jaccard (tech ref 5.6).

    `old` holds every auto chunk of the canvas, orphaned ones included, so undo that restores
    elements brings an orphaned chunk back under its own id. `active` names the old chunks that
    were active (default: all). Matching is greedy and one-to-one: every pair with J above
    `threshold`, highest J first (ties: larger overlap, active before orphaned, then ids).
    An active chunk left unmatched becomes orphaned; its successor is the cluster sharing the most
    elements with it (tie: higher on the page, by `tops`), or None when it shares none.
    """
    active_ids = set(old) if active is None else set(active)
    # Chunk member lists come from cluster(): sorted and free of duplicates.
    owner: dict[str, list[str]] = {}
    for oid, members in old.items():
        for e in members:
            owner.setdefault(e, []).append(oid)

    # old id -> [(cluster index, shared elements)], and candidate pairs above the threshold.
    shared: dict[str, list[tuple[int, int]]] = {}
    pairs = []
    for ci, members in enumerate(clusters):
        counts: dict[str, int] = {}
        for e in members:
            for oid in owner.get(e, ()):
                counts[oid] = counts.get(oid, 0) + 1
        for oid, inter in counts.items():
            shared.setdefault(oid, []).append((ci, inter))
            j = inter / (len(members) + len(old[oid]) - inter)
            if j > threshold:
                pairs.append((-j, -inter, oid not in active_ids, oid, ci))
    pairs.sort()

    assigned: list[str | None] = [None] * len(clusters)
    taken: set[str] = set()
    for *_, oid, ci in pairs:
        if oid not in taken and assigned[ci] is None:
            assigned[ci] = oid
            taken.add(oid)

    successors: dict[str, int | None] = {}
    for oid in sorted(active_ids - taken):
        best = min(shared.get(oid, ()), key=lambda p: (-p[1], tops[p[0]], p[0]), default=None)
        successors[oid] = best[0] if best else None
    return Matching(assigned, successors)
