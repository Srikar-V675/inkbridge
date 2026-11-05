"""Stable chunk ids: match new chunks to old ones (decision 0011, 0029)."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from inkbridge.canvas.chunker.config import ChunkerConfig


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
