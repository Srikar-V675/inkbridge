"""Pure chunker: group scene elements into chunks by proximity. No I/O, no SQLite.

Steps 1-6 of the pipeline in the technical reference (section 5): `cluster` is proximity,
`chunk_scene` adds arrows (merge or link, INK-032), `match_chunks` keeps ids stable (INK-031).
Their constants sit in ChunkerConfig so one object tunes the whole pipeline.
"""

import bisect
import itertools
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
    # chunks are fragile (2 elements gaining 3 is J = 0.4); match_containment below is the
    # opt-in fix (docs/decisions/0029-containment-matching.md). Do not change the threshold.
    match_threshold: float = 0.5
    # None = off. A fraction in (0, 1]: also keep the id when that share of the old chunk survives
    # in the new cluster, or of the new cluster comes from the old chunk (INK-072).
    match_containment: float | None = None
    # A chunk is at most this * its own median stroke size wide or tall (INK-081, decision 0038).
    max_extent: float = 80.0

    def __post_init__(self) -> None:
        for name in ("k", "arrow_merge", "link_reach", "min_median", "max_extent"):
            if not getattr(self, name) > 0:
                raise ValueError(f"ChunkerConfig.{name} must be positive")
        if not 0 <= self.match_threshold < 1:
            raise ValueError("ChunkerConfig.match_threshold must be in [0, 1)")
        if self.match_containment is not None and not 0 < self.match_containment <= 1:
            raise ValueError("ChunkerConfig.match_containment must be in (0, 1] or None")


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


@dataclass(frozen=True)
class Chunking:
    chunks: list[list[str]]  # sorted element ids per chunk, ordered by their smallest id
    links: list[tuple[int, int]]  # arrow links (from, to) as indices into chunks, sorted, unique
    pinned: list[bool]  # per chunk: built from a pin (a manual merge or split, INK-059)


def pin_groups(elements: list[dict[str, Any]], pins: Sequence[Collection[str]]) -> list[list[str]]:
    """The pins reduced to ink that clusters, made disjoint (an earlier pin keeps a shared id).

    Ids that are deleted, drafts, connectors or unknown are dropped (connectors attach by the arrow
    rules instead); bound text and its container always go together (picking either picks both);
    empty pins vanish.
    """
    live = {str(e["id"]): e for e in clustering_elements(elements)}
    # A container and its bound text are one unit, keyed by the container id.
    unit: dict[str, str] = {}
    for eid, e in live.items():
        container = str(e.get("containerId")) if e.get("containerId") is not None else None
        unit[eid] = container if container in live else eid
    members: dict[str, list[str]] = {}
    for eid, key in unit.items():
        members.setdefault(key, []).append(eid)
    taken: set[str] = set()  # unit keys already in an earlier pin
    out = []
    for pin in pins:
        keys = {unit[str(i)] for i in pin if str(i) in live} - taken
        if keys:
            out.append(sorted(i for k in keys for i in members[k]))
            taken |= keys
    return out


def agent_op(e: dict[str, Any]) -> str | None:
    """Op id of an accepted agent element, else None. The id prefix is the trust check."""
    cd = e.get("customData") or {}
    op = cd.get("op_id")
    if cd.get("author") != "agent" or cd.get("draft") or not isinstance(op, str):
        return None
    return op if str(e.get("id", "")).startswith(f"{op}:") else None


def agent_groups(elements: list[dict[str, Any]]) -> list[list[str]]:
    """Each op's accepted elements, in op id order (INK-078, docs/decisions/0044)."""
    by_op: dict[str, list[str]] = {}
    for e in elements:
        op = agent_op(e)
        if op is not None:
            by_op.setdefault(op, []).append(str(e["id"]))
    return [by_op[k] for k in sorted(by_op)]


def _live(element: dict[str, Any]) -> bool:
    return not element.get("isDeleted") and not is_draft(element)


def _box_distance(point: tuple[float, float], box: dict[str, float]) -> float:
    dx = max(box["x"] - point[0], point[0] - (box["x"] + box["width"]), 0.0)
    dy = max(box["y"] - point[1], point[1] - (box["y"] + box["height"]), 0.0)
    return math.hypot(dx, dy)


def _path_length(points: list[list[float]]) -> float:
    return sum(math.dist(a[:2], b[:2]) for a, b in itertools.pairwise(points))


def chunk_scene(
    elements: list[dict[str, Any]],
    config: ChunkerConfig | None = None,
    pins: Sequence[Collection[str]] = (),
) -> Chunking:
    """Proximity clusters plus the arrow rules of tech ref 5.5.

    Each arrow end maps to a chunk: the chunk of its bound element (startBinding/endBinding; a
    binding to an element in no chunk, such as a draft, dangles), else for a free end the nearest
    chunk whose box is within link_reach * median of the end point (x + points[0], x + points[-1]
    in canvas coordinates; inside nested boxes the smallest wins); with neither, it dangles. An arrow whose path is at
    most arrow_merge * median long merges its two chunks; a longer one becomes a link. A dangling
    arrow creates neither. Lines never merge or link. Every live arrow or line joins the chunk of
    its start (else of its end, else forms a chunk of its own), and its bound label goes with it,
    so connectors are part of some chunk's hash and crop.

    `pins` (INK-059, docs/decisions/0024) are manual chunks: each becomes exactly one chunk of its
    ink (see `pin_groups`), nothing joins it by proximity or by an arrow merge (such an arrow
    links instead), and connectors still attach to it.
    """
    config = config or ChunkerConfig()
    manual = pin_groups(elements, pins)
    taken = {i for g in manual for i in g}
    # Accepted agent ink is one forced group per op, so it never merges into user chunks.
    agent = pin_groups(elements, [[i for i in g if i not in taken] for g in agent_groups(elements)])
    groups, median = _proximity(elements, config, exclude=taken | {i for g in agent for i in g})
    first_pinned = len(groups)
    groups = groups + manual + agent
    by_id = {str(e.get("id")): e for e in elements}
    owner = {eid: gi for gi, members in enumerate(groups) for eid in members}
    boxes = [bbox_of([by_id[i] for i in members]) for members in groups]
    reach = config.link_reach * median

    connectors = sorted(
        (e for e in elements if e.get("type") in _CONNECTORS and _live(e)),
        key=lambda e: str(e["id"]),
    )
    labels: dict[str, list[str]] = {}
    for e in elements:
        container_id = e.get("containerId")
        if container_id is not None and _live(e) and str(container_id) in by_id:
            labels.setdefault(str(container_id), []).append(str(e["id"]))

    # Free ends search only the boxes within reach: a uniform grid of reach-wide cells, so a point
    # needs the 3 x 3 cells around it. Boxes too large for the grid are always candidates.
    cells: dict[tuple[int, int], list[int]] = {}
    large: list[int] = []
    for gi, b in enumerate(boxes):
        xs = range(math.floor(b["x"] / reach), math.floor((b["x"] + b["width"]) / reach) + 1)
        ys = range(math.floor(b["y"] / reach), math.floor((b["y"] + b["height"]) / reach) + 1)
        if len(xs) * len(ys) > _MAX_CELLS:
            large.append(gi)
            continue
        for cx in xs:
            for cy in ys:
                cells.setdefault((cx, cy), []).append(gi)

    def end_chunk(c: dict[str, Any], binding: str, point_index: int) -> int | None:
        bound = (c.get(binding) or {}).get("elementId")
        if bound is not None:  # bound to something in no chunk (deleted, a draft): dangling
            return owner.get(str(bound))
        points = c.get("points") or [[0, 0]]
        p = points[point_index]
        point = (c.get("x", 0) + p[0], c.get("y", 0) + p[1])
        if not all(map(math.isfinite, point)):
            return None
        px, py = math.floor(point[0] / reach), math.floor(point[1] / reach)
        candidates = set(large)
        for cx in range(px - 1, px + 2):
            for cy in range(py - 1, py + 2):
                candidates.update(cells.get((cx, cy), ()))
        # Nearest box; an end inside nested boxes picks the smallest, then the first in id order.
        scored = [
            (_box_distance(point, boxes[gi]), boxes[gi]["width"] * boxes[gi]["height"], gi)
            for gi in candidates
        ]
        best = min(scored, default=None)
        if best is None or best[0] > reach:
            return None
        return best[2]

    uf = _UnionFind(len(groups))
    ends = []
    for c in connectors:
        start, end = end_chunk(c, "startBinding", 0), end_chunk(c, "endBinding", -1)
        points = c.get("points") or []
        # A connector needs a drawn path to join or connect anything.
        is_arrow = c.get("type") == "arrow" and len(points) >= 2
        short = _path_length(points) <= config.arrow_merge * median
        free = start is not None and end is not None and max(start, end) < first_pinned
        if is_arrow and short and free:
            uf.union(start, end)
            ends.append((c, start, end, False))
        else:
            ends.append((c, start, end, is_arrow))

    merged: dict[int, list[str]] = {}
    for gi, members in enumerate(groups):
        merged.setdefault(uf.find(gi), []).extend(members)
    raw_links: set[tuple[int, int]] = set()
    extra: list[list[str]] = []
    for c, start, end, links in ends:
        cid = str(c["id"])
        joined = [cid, *labels.get(cid, [])]
        home = start if start is not None else end
        if home is None:
            extra.append(joined)
        else:
            merged[uf.find(home)].extend(joined)
        if links and start is not None and end is not None and uf.find(start) != uf.find(end):
            raw_links.add((uf.find(start), uf.find(end)))

    # (members, root) per chunk; a dangling connector's own chunk has no root and no links.
    final = sorted(
        [(sorted(m), r) for r, m in merged.items()] + [(sorted(m), None) for m in extra],
        key=lambda item: item[0][0],
    )
    index = {r: i for i, (_, r) in enumerate(final) if r is not None}
    links = sorted({(index[a], index[b]) for a, b in raw_links})
    # Pinned and agent groups never union, so each is its own root; only manual ones are pins.
    last_manual = first_pinned + len(manual)
    pinned = [r is not None and first_pinned <= r < last_manual for _, r in final]
    return Chunking([m for m, _ in final], links, pinned)


def connector_ids(elements: list[dict[str, Any]]) -> set[str]:
    """Ids of arrows, lines and their bound labels, live or not (attached ink, not identity)."""
    connectors = {str(e.get("id")) for e in elements if e.get("type") in _CONNECTORS}
    labels = {
        str(e.get("id"))
        for e in elements
        if e.get("containerId") is not None and str(e["containerId"]) in connectors
    }
    return connectors | labels


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
    ignore: Collection[str] = (),
    containment: float | None = None,
) -> Matching:
    """Give new clusters the ids of old chunks by element-id Jaccard (tech ref 5.6).

    `old` holds every auto chunk of the canvas, orphaned ones included, so undo that restores
    elements brings an orphaned chunk back under its own id. `active` names the old chunks that
    were active (default: all). Matching is greedy and one-to-one: every pair with J above
    `threshold`, highest J first (ties: larger overlap, active before orphaned, then ids).
    An active chunk left unmatched becomes orphaned; its successor is the cluster sharing the most
    elements with it (tie: higher on the page, by `tops`), or None when it shares none.

    Ids in `ignore` (connectors and their labels, see `connector_ids`) do not count, so drawing
    or deleting an arrow from a small chunk keeps its id; a chunk of nothing but ignored ids is
    matched on all of them.

    With `containment` (a fraction in (0, 1]) a pair also qualifies when that share of the old
    chunk is inside the cluster or that share of the cluster came from the old chunk. Pairs still
    sort by Jaccard, so a containment-only pair never takes an id from a better Jaccard match.
    """
    active_ids = set(old) if active is None else set(active)
    skip = set(ignore)

    def core(members: Sequence[str]) -> Sequence[str]:
        kept = [e for e in members if e not in skip]
        return kept or members

    old = {oid: core(members) for oid, members in old.items()}
    clusters = [core(members) for members in clusters]
    # Chunk member lists come from chunk_scene(): sorted and free of duplicates.
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
            contained = containment is not None and (
                inter / len(old[oid]) >= containment or inter / len(members) >= containment
            )
            if j > threshold or contained:
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
