"""chunk_scene: chunks and arrow links for a whole scene, with pins and agent groups."""

import itertools
import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from inkbridge.canvas.chunker.clustering import _MAX_CELLS, _proximity, _UnionFind
from inkbridge.canvas.chunker.config import (
    _CONNECTORS,
    ChunkerConfig,
    _live,
    agent_op,
    clustering_elements,
)
from inkbridge.canvas.hashes import bbox_of


@dataclass(frozen=True)
class LinkRow:
    """One v2 link: chunk indices, the connector that makes it and how sure the chunker is."""

    a: int
    b: int
    element_id: str = ""
    confidence: float | None = None
    label: str | None = None


@dataclass(frozen=True)
class Chunking:
    chunks: list[list[str]]  # sorted element ids per chunk, ordered by their smallest id
    links: list[tuple[int, int]]  # arrow links (from, to) as indices into chunks, sorted, unique
    pinned: list[bool]  # per chunk: built from a pin (a manual merge or split, INK-059)
    # v2 only (INK-122): which chunks are a free-ended connector, and one row per linking connector
    connector: list[bool] = field(default_factory=list)
    link_rows: list[LinkRow] = field(default_factory=list)


def pin_groups(
    elements: list[dict[str, Any]],
    pins: Sequence[Collection[str]],
    exclude: Collection[str] = (),
) -> list[list[str]]:
    """The pins reduced to ink that clusters, made disjoint (an earlier pin keeps a shared id).

    Ids that are deleted, drafts, connectors or unknown are dropped (connectors attach by the arrow
    rules instead); bound text and its container always go together (picking either picks both);
    empty pins vanish.
    """
    live = {str(e["id"]): e for e in clustering_elements(elements) if str(e["id"]) not in exclude}
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


def agent_groups(elements: list[dict[str, Any]]) -> list[list[str]]:
    """Each op's accepted elements, in op id order (INK-078, docs/decisions/0044)."""
    by_op: dict[str, list[str]] = {}
    for e in elements:
        op = agent_op(e)
        if op is not None:
            by_op.setdefault(op, []).append(str(e["id"]))
    return [by_op[k] for k in sorted(by_op)]


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
    if config and config.version == "v2":
        # Local import: scene_v2 imports pin_groups, agent_groups, Chunking and the helpers above.
        from inkbridge.canvas.chunker.scene_v2 import chunk_scene_v2

        return chunk_scene_v2(elements, config, pins)
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
