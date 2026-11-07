"""INK-122: chunker v2 (line-aware clusters, connectors as links). Golden guard for v1 first."""

import json
import math
import random
import time
from pathlib import Path

import pytest

from inkbridge.canvas.chunker import ChunkerConfig, chunk_scene, cluster_lines
from inkbridge.canvas.hashes import bbox_of
from inkbridge.canvas.strokes import analyse
from tests.test_chunker import _extent, _layout, arrow, rect, stroke
from tests.test_strokes import circle, line, pen, word

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


# --- Task 1: line-aware clusters ---

V2 = ChunkerConfig.v2()


def sets(groups):
    return {frozenset(g) for g in groups}


def v2(els, config=V2):
    return cluster_lines(els, config, analyse(els))[0]


def v1(els):
    return chunk_scene(els, ChunkerConfig()).chunks


def below(top, i, gap, x=0.0, size=20):
    """A word whose box starts `gap` px under the box of `top`."""
    b = bbox_of([top])
    w = word(i, x, 0, size)
    return word(i, x, b["y"] + b["height"] + gap - bbox_of([w])["y"], size)


def test_default_config_is_v1_and_v2_factory_values():
    d = ChunkerConfig()
    assert (d.version, d.arrow_merge, d.link_reach) == ("v1", 6.0, 3.0)
    c = ChunkerConfig.v2()
    assert (c.version, c.arrow_merge, c.link_reach) == ("v2", 1.0, 2.0)
    assert (c.k, c.next_line, c.long_stroke) == (1.5, 0.5, 2.0)
    with pytest.raises(ValueError):
        ChunkerConfig(version="v3")
    with pytest.raises(ValueError):
        ChunkerConfig(next_line=0)


def test_same_line_words_join_at_1_5_T_but_adjacent_lines_need_0_5_T():
    a = word("a", 0, 0)
    same = [a, word("b", 45, 0)]  # 25 px apart on one line, T = 20
    assert analyse(same).scale == 20
    assert sets(v2(same)) == {frozenset("ab")} and len(v1(same)) == 1
    apart = [a, below(a, "b", 25)]
    assert len(v1(apart)) == 1  # one k does not tell a line from a word
    assert len(v2(apart)) == 2
    assert len(v2([a, below(a, "b", 8)])) == 1


def test_adjacent_line_needs_horizontal_overlap():
    a = word("a", 0, 0)
    b = below(a, "b", 15, x=40)  # no overlap in x
    assert len(v2([a, b])) == 2
    assert len(v2([a, below(a, "b", 8, x=10)])) == 1


def test_long_curved_stroke_does_not_join_by_bounding_box():
    # A spiral round an empty middle: its box holds the word, its ink stays 40 px away.
    arc = pen(
        "arc",
        [
            ((50 + 60 * u) * math.cos(10 * u), (50 + 60 * u) * math.sin(10 * u))
            for u in (k / 59 for k in range(60))
        ],
    )
    inside = word("w", -10, -5)
    els = [arc, inside]
    assert analyse(els).kinds["arc"] == "writing"
    assert len(v1(els)) == 1  # the boxes overlap
    assert sets(v2(els)) == {frozenset(["arc"]), frozenset(["w"])}
    near = [arc, word("w", 35, -5)]  # touching the ink
    assert len(v2(near)) == 1


def test_container_unions_what_it_contains():
    a, b = word("a", -10, -30), word("b", -10, 30)
    assert len(v2([a, b])) == 2
    els = [circle("c", 0, 0, 60), a, b]
    assert analyse(els).kinds["c"] == "container"
    assert sets(v2(els)) == {frozenset(["a", "b", "c"])}


def test_underline_joins_the_writing_above():
    a = word("a", 0, 0)
    b = bbox_of([a])
    u = line("u", 0, b["y"] + b["height"] + 14, 20, b["y"] + b["height"] + 14)
    els = [a, u]
    assert analyse(els).kinds["u"] == "underline"
    assert len(v2(els)) == 1


def test_local_scale_and_cap_still_apply():
    page = [word(f"p{r}-{c}", c * 25, 3000 + r * 200) for r in range(4) for c in range(10)]
    small = [word(f"s{c}", 20000 + c * 5, 0, 4) for c in range(10)]
    small += [word(f"t{c}", 20000 + 50 + 20 + c * 5, 0, 4) for c in range(10)]  # 20 px right
    groups = sets(v2(page + small))
    assert frozenset(f"s{c}" for c in range(10)) in groups
    assert frozenset(f"t{c}" for c in range(10)) in groups
    row = [word(f"r{c}", c * 25, 0) for c in range(200)]
    by_id = {e["id"]: e for e in row}
    chunks = v2(row)
    assert len(chunks) > 1
    for c in chunks:
        assert max(_extent(by_id, c)) <= V2.max_extent * 20 + 25


def test_v2_cluster_is_input_order_independent_and_partitions():
    rng = random.Random(5)
    els = [word(f"s{i}", rng.uniform(0, 400), rng.uniform(0, 400)) for i in range(60)]
    shuffled = els[:]
    random.Random(6).shuffle(shuffled)
    assert v2(els) == v2(shuffled)
    flat = [i for g in v2(els) for i in g]
    assert sorted(flat) == sorted(e["id"] for e in els)


def test_5000_elements_v2_cluster_in_under_2s():
    els = [stroke(f"s{r}-{c}", c * 14, r * 60) for r in range(50) for c in range(100)]
    start = time.perf_counter()
    chunks = v2(els)
    assert time.perf_counter() - start < 2.0
    assert len(chunks) == 50
    rng = random.Random(7)
    hatch = [stroke(f"h{i}", (i % 70) * 1.0, (i // 70) * 1.0) for i in range(3000)]
    pile = [stroke(f"p{i}", 1000 + rng.uniform(0, 3), rng.uniform(0, 3)) for i in range(2500)]
    start = time.perf_counter()
    chunks = v2(hatch + pile)
    assert time.perf_counter() - start < 2.0
    assert len(chunks) == 2
