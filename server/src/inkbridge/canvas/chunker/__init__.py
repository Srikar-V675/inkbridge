"""Pure chunker: group scene elements into chunks by proximity. No I/O, no SQLite.

Steps 1-6 of the pipeline in the technical reference (section 5): `cluster` is proximity,
`chunk_scene` adds arrows (merge or link, INK-032), `match_chunks` keeps ids stable (INK-031).
Their constants sit in ChunkerConfig so one object tunes the whole pipeline.

The package re-exports every name so `from inkbridge import db` and `db.<name>` keep working."""

from inkbridge.canvas.chunker.clustering import (
    _LEVEL_FACTOR,
    _MAX_CELLS,
    _box,
    _cap,
    _gap,
    _own_scale,
    _proximity,
    _UnionFind,
    cluster,
    proximity_threshold,
)
from inkbridge.canvas.chunker.config import (
    _CONNECTORS,
    _SHAPES,
    ChunkerConfig,
    _live,
    _takes_part,
    agent_op,
    clustering_elements,
    connector_ids,
    is_draft,
    stroke_connector_ids,
)
from inkbridge.canvas.chunker.connectors import EndIndex
from inkbridge.canvas.chunker.lines import cluster_lines
from inkbridge.canvas.chunker.matching import Matching, match_chunks
from inkbridge.canvas.chunker.order import kind_hint, reading_order
from inkbridge.canvas.chunker.scene import (
    Chunking,
    LinkRow,
    _box_distance,
    _path_length,
    agent_groups,
    chunk_scene,
    pin_groups,
)
from inkbridge.canvas.chunker.scene_v2 import chunk_scene_v2

__all__ = [
    "_CONNECTORS",
    "_LEVEL_FACTOR",
    "_MAX_CELLS",
    "_SHAPES",
    "ChunkerConfig",
    "Chunking",
    "EndIndex",
    "LinkRow",
    "Matching",
    "_UnionFind",
    "_box",
    "_box_distance",
    "_cap",
    "_gap",
    "_live",
    "_own_scale",
    "_path_length",
    "_proximity",
    "_takes_part",
    "agent_groups",
    "agent_op",
    "chunk_scene",
    "chunk_scene_v2",
    "cluster",
    "cluster_lines",
    "clustering_elements",
    "connector_ids",
    "is_draft",
    "kind_hint",
    "match_chunks",
    "pin_groups",
    "proximity_threshold",
    "reading_order",
    "stroke_connector_ids",
]
