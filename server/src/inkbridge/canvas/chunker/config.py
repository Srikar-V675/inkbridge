"""What takes part in chunking: settings and element filters."""

from dataclasses import dataclass
from typing import Any

from inkbridge.canvas.strokes import StrokeKinds

# Elements that join chunks through other rules, not by proximity.
_CONNECTORS = {"arrow", "line"}
_SHAPES = {"rectangle", "ellipse", "diamond", "arrow", "line", "frame"}


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
    # Chunker v2 (INK-122, decision 0081). "v1" is the original; the fields below only matter to v2
    # and are in units of T, the writing scale from the stroke kinds (start values, E5 tunes them).
    version: str = "v1"
    next_line: float = (
        0.5  # a line below joins when closer than this * T and the boxes overlap in x
    )
    long_stroke: float = 4.0  # a stroke longer than this * T joins by its ink, not its box

    @classmethod
    def v2(cls, **kw: Any) -> "ChunkerConfig":
        """The v2 settings: connectors merge only when a tick (1 T) and link within 2 T."""
        return cls(
            version="v2", arrow_merge=1.0, link_reach=2.0, **{"next_line": 2.0, "k": 2.0, **kw}
        )

    def __post_init__(self) -> None:
        for name in (
            "k",
            "arrow_merge",
            "link_reach",
            "min_median",
            "max_extent",
            "next_line",
            "long_stroke",
        ):
            if not getattr(self, name) > 0:
                raise ValueError(f"ChunkerConfig.{name} must be positive")
        if self.version not in ("v1", "v2"):
            raise ValueError("ChunkerConfig.version must be 'v1' or 'v2'")
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


def agent_op(e: dict[str, Any]) -> str | None:
    """Op id of an accepted agent element, else None. The id prefix is the trust check."""
    cd = e.get("customData") or {}
    op = cd.get("op_id")
    if cd.get("author") != "agent" or cd.get("draft") or not isinstance(op, str):
        return None
    return op if str(e.get("id", "")).startswith(f"{op}:") else None


def _live(element: dict[str, Any]) -> bool:
    return not element.get("isDeleted") and not is_draft(element)


def connector_ids(elements: list[dict[str, Any]]) -> set[str]:
    """Ids of arrows, lines and their bound labels, live or not (attached ink, not identity)."""
    connectors = {str(e.get("id")) for e in elements if e.get("type") in _CONNECTORS}
    labels = {
        str(e.get("id"))
        for e in elements
        if e.get("containerId") is not None and str(e["containerId"]) in connectors
    }
    return connectors | labels


def stroke_connector_ids(kinds: StrokeKinds) -> set[str]:
    """Ids the stroke kinds keep out of v2 chunks: connectors (pen and native) and their heads."""
    return {i for i, k in kinds.kinds.items() if k == "connector"} | set(kinds.head_of)
