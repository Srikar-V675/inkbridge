"""INK-122: chunker v2 (line-aware clusters, connectors as links). Golden guard for v1 first."""

import json
from pathlib import Path

from inkbridge.canvas.chunker import ChunkerConfig, chunk_scene
from tests.test_chunker import _layout, arrow, rect, stroke

GOLDEN = Path(__file__).parent / "data" / "chunker_v1_golden.json"


def golden_scenes():
    """Three scenes built from deterministic inputs only (random.Random(seed))."""
    mixed = _layout(1) + [
        {**e, "id": "z" + e["id"], "x": e["x"] + 50000} for e in _layout(2, scale=0.2)
    ]
    near = [rect("a", 0, 0, 100, 100), rect("b", 500, 0, 100, 100)]
    far = [rect("c", 0, 2000, 100, 100), rect("d", 2000, 0, 100, 100), rect("e", 0, 4000, 100, 100)]
    nodes = [
        *near,
        *far,
        arrow("bound", 100, 50, 1900, start="c", end="d"),
        arrow("tick", 100, 50, 400, start="a", end="b"),
        arrow("free", 100, 2050, 1800),
    ]
    row = [stroke(f"s{i}", i * 14, 0) for i in range(60)]
    return {
        "mixed": (mixed, []),
        "nodes": (nodes, []),
        "row": (row, []),
        "row_pinned": (row, [["s3", "s4"]]),
    }


def golden_output():
    out = {}
    configs = {"default": ChunkerConfig(), "tuned": ChunkerConfig(k=0.8, arrow_merge=2)}
    for sname, (els, pins) in golden_scenes().items():
        for cname, cfg in configs.items():
            r = chunk_scene(els, cfg, pins=pins)
            out[f"{sname}/{cname}"] = {
                "chunks": r.chunks,
                "links": [list(p) for p in r.links],
                "pinned": r.pinned,
            }
    return out


def test_v1_output_is_unchanged_by_this_ticket():
    assert golden_output() == json.loads(GOLDEN.read_text())
