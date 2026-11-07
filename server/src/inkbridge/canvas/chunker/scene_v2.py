"""chunk_scene for chunker v2: line-aware clusters, connectors as links (INK-122, decision 0081).

Pen connectors (stroke kind `connector`), their heads, native arrows and lines and their labels
are never chunk members, so moving or deleting an arrow changes no chunk hash. Each connector
becomes a merge (a tick), a link row, nothing (both ends in one chunk) or, with a free end, a
chunk of its own with kind `connector`.
"""

import math
from collections.abc import Collection, Sequence
from typing import Any

from inkbridge.canvas.chunker.clustering import _UnionFind
from inkbridge.canvas.chunker.config import (
    ChunkerConfig,
    _live,
    connector_ids,
    stroke_connector_ids,
)
from inkbridge.canvas.chunker.connectors import EndIndex, end_points
from inkbridge.canvas.chunker.lines import cluster_lines
from inkbridge.canvas.chunker.scene import (
    Chunking,
    LinkRow,
    _path_length,
    agent_groups,
    pin_groups,
)
from inkbridge.canvas.hashes import bbox_of
from inkbridge.canvas.strokes import analyse


def _confidence(evidenced: bool, worst: float, reach: float) -> float:
    value = 0.4 + 0.3 * evidenced + 0.3 * (1 - min(worst / reach, 1.0))
    return round(min(max(value, 0.0), 1.0), 2)


def chunk_scene_v2(
    elements: list[dict[str, Any]],
    config: ChunkerConfig,
    pins: Sequence[Collection[str]] = (),
) -> Chunking:
    kinds = analyse(elements)
    skip = stroke_connector_ids(kinds) | connector_ids(elements)  # strokes, heads, native, labels
    manual = pin_groups(elements, pins, exclude=skip)
    taken = {i for g in manual for i in g}
    agent = pin_groups(
        elements, [[i for i in g if i not in taken] for g in agent_groups(elements)], exclude=skip
    )
    groups, t = cluster_lines(
        elements, config, kinds, exclude=taken | {i for g in agent for i in g}
    )
    first_pinned = len(groups)
    groups = groups + manual + agent
    by_id = {str(e.get("id")): e for e in elements}
    owner = {eid: gi for gi, members in enumerate(groups) for eid in members}
    boxes = [bbox_of([by_id[i] for i in members]) for members in groups]
    reach = config.link_reach * t
    index = EndIndex(boxes, reach) if boxes else None

    labels: dict[str, list[str]] = {}
    for e in elements:
        container_id = e.get("containerId")
        if container_id is not None and _live(e) and str(container_id) in by_id:
            labels.setdefault(str(container_id), []).append(str(e["id"]))
    heads: dict[str, list[str]] = {}
    for head, shaft in kinds.head_of.items():
        heads.setdefault(shaft, []).append(head)

    def end_of(c: dict[str, Any], binding: str, point: tuple[float, float]):
        """(group, distance to its box) of one connector end, or None when the end is free."""
        bound = (c.get(binding) or {}).get("elementId")
        if bound is not None:  # bound to ink in no chunk (deleted, a draft) is a free end
            gi = owner.get(str(bound))
            return None if gi is None else (gi, 0.0)
        return index.nearest(point) if index else None

    uf = _UnionFind(len(groups))
    found = []  # (connector, start group, end group, evidenced, worst distance, direction)
    free: list[dict[str, Any]] = []
    connectors = sorted(
        (e for e in elements if kinds.kinds.get(str(e.get("id"))) == "connector" and _live(e)),
        key=lambda e: str(e["id"]),
    )
    for c in connectors:
        ends = end_points(c)
        if ends is None:
            continue  # no drawn path: nothing to join or connect
        start, end = end_of(c, "startBinding", ends[0]), end_of(c, "endBinding", ends[1])
        if start is None or end is None:
            free.append(c)
            continue
        cid = str(c["id"])
        head_boxes = [bbox_of([by_id[h]]) for h in heads.get(cid, [])]
        flip = False
        if head_boxes:  # the head sits at the end the connector points to
            hx = head_boxes[0]["x"] + head_boxes[0]["width"] / 2
            hy = head_boxes[0]["y"] + head_boxes[0]["height"] / 2
            flip = math.dist((hx, hy), ends[0]) < math.dist((hx, hy), ends[1])
        arrowhead = c.get("type") == "arrow" and bool(
            c.get("endArrowhead") or c.get("startArrowhead")
        )
        both_bound = c.get("startBinding") is not None and c.get("endBinding") is not None
        evidenced = bool(head_boxes) or arrowhead or both_bound
        worst = max(start[1], end[1])
        sg, eg = (end[0], start[0]) if flip else (start[0], end[0])
        found.append((c, sg, eg, evidenced, worst))
        short = _path_length(c.get("points") or []) <= config.arrow_merge * t
        if short and sg != eg and max(sg, eg) < first_pinned:
            uf.union(sg, eg)  # a tick: the two chunks are one, the tick itself is in neither

    merged: dict[int, list[str]] = {}
    for gi, members in enumerate(groups):
        merged.setdefault(uf.find(gi), []).extend(members)
    extra: list[list[str]] = []
    for c in free:
        cid = str(c["id"])
        extra.append([cid, *heads.get(cid, []), *labels.get(cid, [])])

    # (members, root, is a connector chunk) per chunk, ordered by smallest id as in v1.
    final = sorted(
        [(sorted(m), r, False) for r, m in merged.items()]
        + [(sorted(m), None, True) for m in extra],
        key=lambda item: item[0][0],
    )
    position = {r: i for i, (_, r, _) in enumerate(final) if r is not None}
    rows = []
    for c, sg, eg, evidenced, worst in found:
        a, b = uf.find(sg), uf.find(eg)
        if a == b:
            continue  # both ends in one chunk (or a tick that merged them): nothing to link
        text = next(
            (str(by_id[i]["text"]) for i in labels.get(str(c["id"]), []) if by_id[i].get("text")),
            None,
        )
        rows.append(
            LinkRow(
                position[a], position[b], str(c["id"]), _confidence(evidenced, worst, reach), text
            )
        )
    rows.sort(key=lambda r: (r.a, r.b, r.element_id))
    links = sorted({(r.a, r.b) for r in rows})
    last_manual = first_pinned + len(manual)
    pinned = [r is not None and first_pinned <= r < last_manual for _, r, _ in final]
    return Chunking([m for m, _, _ in final], links, pinned, [x for _, _, x in final], rows)
