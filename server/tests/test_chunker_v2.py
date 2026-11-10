"""INK-122: chunker v2 (line-aware clusters, connectors as links). Golden guard for v1 first."""

import json
import math
import random
import time
from pathlib import Path

import pytest

from inkbridge.canvas.chunker import (
    ChunkerConfig,
    chunk_scene,
    cluster_lines,
    connector_ids,
    pin_groups,
    stroke_connector_ids,
)
from inkbridge.canvas.hashes import bbox_of, content_hash, stroke_hash
from inkbridge.canvas.strokes import analyse
from tests.test_chunker import _extent, _layout, arrow, rect, stroke
from tests.test_strokes import circle, line, native, pen, vee, word

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
    assert (c.k, c.next_line, c.long_stroke) == (2.0, 2.0, 4.0)  # INK-195, decision 0110
    with pytest.raises(ValueError):
        ChunkerConfig(version="v3")
    with pytest.raises(ValueError):
        ChunkerConfig(next_line=0)


def test_same_line_words_join_at_2_T_but_adjacent_lines_need_2_T():
    a = word("a", 0, 0)
    same = [a, word("b", 45, 0)]  # 25 px apart on one line, T = 20
    assert analyse(same).scale == 20
    assert sets(v2(same)) == {frozenset("ab")} and len(v1(same)) == 1
    apart = [a, below(a, "b", 45)]  # beyond next_line * T = 40
    assert len(v2(apart)) == 2
    assert len(v2([a, below(a, "b", 35)])) == 1
    assert len(v2([a, below(a, "b", 8)])) == 1


def test_adjacent_line_needs_horizontal_overlap():
    a = word("a", 0, 0)
    b = below(a, "b", 15, x=70)  # 50 px right of a: beyond k * T
    assert len(v2([a, b])) == 2
    assert len(v2([a, below(a, "b", 15, x=40)])) == 1  # a diagonal neighbour joins
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


# --- Task 2: connectors ---


def words(prefix, x, y, n=3):
    return [word(f"{prefix}{k}", x + 30 * k, y) for k in range(n)]


def hub_and_spoke(head_at_hub=False):
    """A hub of six words, four spokes of three, four pen connectors with heads, one native arrow."""
    hub = [*words("h", 0, 0), *words("g", 0, 14)]
    spokes = [
        *words("r", 500, 0),
        *words("l", -500, 0),
        *words("u", 0, -500),
        *words("d", 0, 500),
    ]
    # (id, shaft start, shaft end, head tip)
    pen_links = [
        ("cr", (85, 8), (495, 8), (485, 8)),
        ("cl", (-5, 8), (-415, 8), (-425, 8)),
        ("cu", (40, -8), (40, -485), (35, -485)),
        ("cd", (40, 25), (40, 495), (35, 495)),
    ]
    out = [*hub, *spokes]
    for n, (cid, a, b, tip) in enumerate(pen_links):
        if head_at_hub:
            tip = (a[0] - 3, a[1]) if a[0] != b[0] else (a[0] - 5, a[1])
        out.append(line(cid, *a, *b, index=f"a{n}0"))
        out.append(vee(f"{cid}-head", *tip, index=f"a{n}1"))
    na = native("na", "arrow", 580, 5)
    na.update(
        points=[[0, 0], [-540, 495]],
        startBinding={"elementId": "r2"},
        endBinding={"elementId": "d0"},
    )
    label = {"id": "na-label", "type": "text", "containerId": "na", "x": 300, "y": 250, "text": "x"}
    na["boundElements"] = [{"id": "na-label", "type": "text"}]
    return [*out, na, label]


def chunk_index(r, eid):
    return next(i for i, c in enumerate(r.chunks) if eid in c)


def test_fixture_is_what_the_tests_assume():
    kinds = analyse(hub_and_spoke())
    for cid in ("cr", "cl", "cu", "cd"):
        assert kinds.kinds[cid] == "connector"
        assert kinds.kinds[f"{cid}-head"] == "head"
        assert kinds.head_of[f"{cid}-head"] == cid
    assert kinds.scale == 20


def test_hub_and_spoke_has_links_and_no_chunk_contains_a_connector():
    els = hub_and_spoke()
    r = chunk_scene(els, ChunkerConfig.v2())
    assert len(r.chunks) == 5 and len(r.links) > 0
    members = {i for c in r.chunks for i in c}
    out = {"cr", "cl", "cu", "cd", "na", "na-label"} | {
        f"{c}-head" for c in ("cr", "cl", "cu", "cd")
    }
    assert not (members & out)
    assert members == {e["id"] for e in els} - out
    ids = [row.element_id for row in r.link_rows]
    assert sorted(ids) == ["cd", "cl", "cr", "cu", "na"]
    assert r.connector == [False] * 5


def test_link_direction_follows_the_head():
    r = chunk_scene(hub_and_spoke(), ChunkerConfig.v2())
    hub = chunk_index(r, "h0")
    rows = {row.element_id: row for row in r.link_rows}
    assert all(rows[c].a == hub for c in ("cr", "cl", "cu", "cd"))
    assert rows["cr"].b == chunk_index(r, "r0")
    flipped = chunk_scene(hub_and_spoke(head_at_hub=True), ChunkerConfig.v2())
    hub = chunk_index(flipped, "h0")
    assert all(row.b == hub for row in flipped.link_rows if row.element_id.startswith("c"))


def hashes(els, r):
    by_id = {e["id"]: e for e in els}
    return [
        (
            c,
            stroke_hash([by_id[i] for i in c]),
            content_hash([by_id[i] for i in c]),
            bbox_of([by_id[i] for i in c]),
        )
        for c in r.chunks
    ]


def test_moving_an_arrow_changes_no_chunk_hash_or_box():
    els = hub_and_spoke()
    before = hashes(els, chunk_scene(els, ChunkerConfig.v2()))
    moved = [
        {**e, "x": e["x"] + 5, "y": e["y"] + 5} if e["id"] in ("cr", "cr-head") else e for e in els
    ]
    r = chunk_scene(moved, ChunkerConfig.v2())
    assert len(r.link_rows) == 5
    assert hashes(moved, r) == before
    gone = [e for e in els if e["id"] not in ("cr", "cr-head")]
    assert hashes(gone, chunk_scene(gone, ChunkerConfig.v2())) == before


def test_free_end_connector_is_its_own_connector_chunk():
    hub = words("h", 0, 0)
    els = [*hub, line("c", 85, 8, 285, 8, index="a0"), vee("c-head", 275, 8, index="a1")]
    assert analyse(els).head_of == {"c-head": "c"}
    r = chunk_scene(els, ChunkerConfig.v2())
    assert r.chunks == [["c", "c-head"], ["h0", "h1", "h2"]]
    assert r.connector == [True, False] and r.link_rows == []
    arr = native("na", "arrow", 85, 8)
    arr["points"] = [[0, 0], [300, 0]]
    label = {"id": "nl", "type": "text", "containerId": "na", "x": 200, "y": 0, "text": "why"}
    r = chunk_scene([*hub, arr, label], ChunkerConfig.v2())
    assert r.chunks == [["h0", "h1", "h2"], ["na", "nl"]]
    assert r.connector == [False, True] and r.links == []


def two_words(gap_between):
    return [word("a", 0, 0), word("b", 20 + gap_between, 0)]


def tick(length, x=45):
    t = native("t", "arrow", x, 0)
    t["points"] = [[0, 0], [length, 0]]
    return t


def test_tick_merges_and_longer_connector_links():
    els = two_words(80)  # 80 apart: two chunks
    assert len(chunk_scene(els, ChunkerConfig.v2()).chunks) == 2
    r = chunk_scene([*els, tick(20)], ChunkerConfig.v2())
    assert r.chunks == [["a", "b"]] and r.link_rows == []
    r = chunk_scene([*els, tick(60)], ChunkerConfig.v2())
    assert r.chunks == [["a"], ["b"]]
    assert [(x.a, x.b, x.element_id) for x in r.link_rows] == [(0, 1, "t")]


def test_connector_inside_one_chunk_makes_nothing():
    els = [*words("h", 0, 0), native("n", "arrow", 2, 4)]
    els[-1]["points"] = [[0, 0], [50, 0]]
    r = chunk_scene(els, ChunkerConfig.v2())
    assert r.chunks == [["h0", "h1", "h2"]] and r.link_rows == [] and r.connector == [False]


def test_connector_to_pinned_chunk_links_instead_of_merging():
    els = [*two_words(80), tick(20)]
    r = chunk_scene(els, ChunkerConfig.v2(), pins=[["a"]])
    assert r.chunks == [["a"], ["b"]] and r.pinned == [True, False]
    assert [x.element_id for x in r.link_rows] == ["t"]


def test_pins_drop_connector_ids():
    els = hub_and_spoke()
    skip = stroke_connector_ids(analyse(els)) | connector_ids(els)
    assert pin_groups(els, [["h0", "cr", "cr-head", "na"]], exclude=skip) == [["h0"]]
    r = chunk_scene(els, ChunkerConfig.v2(), pins=[["h0", "cr", "cr-head", "na"]])
    assert ["h0"] in r.chunks and r.pinned.count(True) == 1


def test_link_confidence_orders_by_evidence():
    hub = words("h", 0, 0)
    far = words("f", 500, 0)
    more = words("m", 500, 300)
    els = [
        *hub,
        *far,
        *more,
        line("tight", 85, 8, 495, 8, index="a00"),
        vee("tight-head", 485, 8, index="a01"),
        line("loose", 40, 25, 540, 330, index="a10"),
    ]
    # the headless one ends 36 px (1.8 T) above the far box of "more"
    els[-1] = pen(  # a hook at the tip is evidence, but weaker than a head
        "loose", [(40, 25), (290, 130), (540, 300 - 4 - 36), (505, 300 - 4 - 36 - 2)], "a10"
    )
    r = chunk_scene(els, ChunkerConfig.v2())
    rows = {x.element_id: x for x in r.link_rows}
    assert set(rows) == {"tight", "loose"}
    assert rows["tight"].confidence > rows["loose"].confidence
    assert all(0 <= x.confidence <= 1 for x in r.link_rows)


def test_v1_scene_still_ignores_new_fields():
    r = chunk_scene(hub_and_spoke(), ChunkerConfig())
    assert r.link_rows == [] and r.connector == []


def flow(gap, w=160, h=70):
    els = [rect(f"b{i}", i * (w + gap), 0, w, h) for i in range(4)]
    els += [
        arrow(f"a{i}", i * (w + gap) + w, 35, gap, start=f"b{i}", end=f"b{i + 1}") for i in range(3)
    ]
    return els


# Arrows no longer than the median element are ticks and merge their boxes (techref 5.x).
@pytest.mark.parametrize(
    "gap,chunks,links", [(80, 1, 0), (160, 1, 0), (200, 4, 3), (240, 4, 3), (400, 4, 3)]
)
def test_v2_flowchart_boxes_are_separate_chunks_joined_by_links(gap, chunks, links):
    r = chunk_scene(flow(gap), V2)
    assert (len(r.chunks), len(r.links)) == (chunks, links)


def test_v2_overlapping_or_nested_shapes_still_join():
    assert sets(v2([rect("o", 0, 0, 300, 200), rect("i", 50, 50, 100, 60)])) == {frozenset("oi")}


def test_v2_text_near_a_shape_still_joins_by_proximity():
    text = {"id": "t", "type": "text", "x": 170, "y": 20, "width": 60, "height": 30, "text": "hi"}
    assert sets(v2([rect("r", 0, 0, 160, 70), text])) == {frozenset({"r", "t"})}


def _curly(i, x, y, w=6000, h=3000, periods=2):
    """A page-sized wavy freedraw: low net / path, few reversals, so it reads as writing."""
    pts = [
        (x + w * u, y + h / 2 + (h / 2) * math.sin(2 * math.pi * periods * u))
        for u in (k / 80 for k in range(81))
    ]
    return pen(i, pts)


def _block(
    prefix, x0, y0, lines=4, words=8, strokes=3, stroke_w=50, stroke_h=40, gap=20, pitch=100
):
    """Paragraph of short strokes: `gap` px between strokes, `pitch` px between line tops."""
    out = []
    for r in range(lines):
        for w in range(words):
            for s in range(strokes):
                x = x0 + (w * strokes + s) * (stroke_w + gap)
                out.append(word(f"{prefix}{r}-{w}-{s}", x, y0 + r * pitch, stroke_w))
    return out


def test_page_sized_curly_stroke_does_not_shatter_a_paragraph():
    para = _block("p", 2000, 1000)
    curls = [_curly(f"c{k}", 0, 200 + k * 50) for k in range(3)]
    els = [*para, *curls]
    assert all(analyse(els).kinds[c["id"]] == "writing" for c in curls)
    assert len(chunk_scene(els, ChunkerConfig.v2()).chunks) <= 4


def _wide_block(prefix, x0, y0, lines=6, words=6, strokes=3, t=20.0):
    """Handwriting block: word gap 1.4 T, line pitch 1.1 T, each line drifting 15 px downward."""
    out = []
    word_w = strokes * t + (strokes - 1) * 0.4 * t
    width = words * (word_w + 1.4 * t)
    for r in range(lines):
        for w in range(words):
            for s in range(strokes):
                x = x0 + w * (word_w + 1.4 * t) + s * 1.4 * t
                y = y0 + r * 1.1 * t + 15 * (x - x0) / width
                pts = [(x + t * k / 7, y + 0.45 * t * math.sin(k * 1.3)) for k in range(8)]
                out.append(pen(f"{prefix}{r}-{w}-{s}", pts))
    return out


def test_wide_handwriting_lines_form_one_block():
    els = _wide_block("a", 0, 0)
    assert analyse(els).scale == 20
    assert len(chunk_scene(els, ChunkerConfig.v2()).chunks) == 1


def test_two_paragraphs_a_screen_apart_stay_two():
    els = _wide_block("a", 0, 0) + _wide_block("b", 0, 40 * 20.0)
    assert len(chunk_scene(els, ChunkerConfig.v2()).chunks) == 2
