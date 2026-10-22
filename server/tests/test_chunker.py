import random
import time

from inkbridge.chunker import ChunkerConfig, cluster, kind_hint, reading_order


def stroke(i, x, y, w=10, h=20, **extra):
    return {
        "id": i,
        "type": "freedraw",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "points": [[0, 0], [w, h]],
        "pressures": [0.5, 0.5],
        "isDeleted": False,
        **extra,
    }


def rect(i, x, y, w=100, h=50, **extra):
    return {"id": i, "type": "rectangle", "x": x, "y": y, "width": w, "height": h, **extra}


def as_sets(chunks):
    return {frozenset(c) for c in chunks}


def test_two_close_strokes_form_one_chunk():
    assert as_sets(cluster([stroke("a", 0, 0), stroke("b", 15, 0)])) == {frozenset("ab")}


def test_far_apart_strokes_form_two_chunks():
    assert as_sets(cluster([stroke("a", 0, 0), stroke("b", 500, 0)])) == {
        frozenset("a"),
        frozenset("b"),
    }


def test_long_diagram_stays_one_chunk():
    boxes = [rect(f"r{i}", i * 110, 0) for i in range(20)]
    assert len(cluster(boxes)) == 1


def test_empty_scene_has_no_chunks():
    assert cluster([]) == []


def test_deleted_and_draft_elements_are_excluded():
    els = [
        stroke("a", 0, 0),
        stroke("gone", 12, 0, isDeleted=True),
        stroke("draft", 14, 0, customData={"author": "agent", "draft": True, "op_id": "o1"}),
    ]
    assert cluster(els) == [["a"]]


def test_accepted_draft_joins_chunks():
    els = [stroke("a", 0, 0), stroke("acc", 14, 0, customData={"author": "agent", "draft": False})]
    assert cluster(els) == [["a", "acc"]]


def test_bound_text_joins_its_container_regardless_of_distance():
    els = [
        rect("box", 0, 0),
        {
            "id": "label",
            "type": "text",
            "x": 5000,
            "y": 5000,
            "width": 20,
            "height": 20,
            "containerId": "box",
        },
        stroke("far", 900, 0),
    ]
    assert as_sets(cluster(els)) == {frozenset({"box", "label"}), frozenset({"far"})}


def test_arrows_and_lines_do_not_take_part():
    els = [
        rect("a", 0, 0),
        rect("b", 400, 0),
        {
            "id": "arr",
            "type": "arrow",
            "x": 100,
            "y": 25,
            "width": 300,
            "height": 0,
            "points": [[0, 0], [300, 0]],
        },
        {
            "id": "ln",
            "type": "line",
            "x": 0,
            "y": 0,
            "width": 5,
            "height": 5,
            "points": [[0, 0], [5, 5]],
        },
    ]
    assert as_sets(cluster(els)) == {frozenset("a"), frozenset("b")}


def test_median_floor_keeps_tiny_dots_from_collapsing_the_threshold():
    dots = [stroke("a", 0, 0, w=1, h=1), stroke("b", 4, 0, w=1, h=1)]
    assert len(cluster(dots)) == 1  # gap 3 < 1.5 * floor 4


def test_k_is_configurable():
    els = [stroke("a", 0, 0), stroke("b", 40, 0)]  # gap 30, median 20
    assert len(cluster(els)) == 2
    assert len(cluster(els, ChunkerConfig(k=2.0))) == 1


def _layout(seed, scale=1.0, n=60):
    rng = random.Random(seed)
    return [
        stroke(
            f"s{i}",
            rng.uniform(0, 400) * scale,
            rng.uniform(0, 400) * scale,
            w=10 * scale,
            h=20 * scale,
        )
        for i in range(n)
    ]


def test_result_is_a_partition_of_live_clustering_elements():
    els = _layout(1)
    ids = [i for c in cluster(els) for i in c]
    assert sorted(ids) == sorted(e["id"] for e in els)


def test_result_is_independent_of_input_order():
    els = _layout(2)
    shuffled = els[:]
    random.Random(3).shuffle(shuffled)
    assert cluster(els) == cluster(shuffled)


def test_scaling_the_layout_does_not_change_the_clustering():
    assert as_sets(cluster(_layout(4, 1.0))) == as_sets(cluster(_layout(4, 2.0)))


def test_5000_elements_cluster_in_under_a_second():
    els = [stroke(f"s{r}-{c}", c * 14, r * 60) for r in range(50) for c in range(100)]
    start = time.perf_counter()
    chunks = cluster(els)
    assert time.perf_counter() - start < 1.0
    assert len(chunks) == 50  # one chunk per text row


def test_reading_order_is_rows_top_to_bottom_then_left_to_right():
    boxes = {
        "c": {"x": 0, "y": 200, "width": 100, "height": 40},
        "b": {"x": 300, "y": 5, "width": 100, "height": 40},
        "a": {"x": 0, "y": 0, "width": 100, "height": 40},
    }
    assert reading_order(boxes) == ["a", "b", "c"]


def test_reading_order_row_tolerance_reads_a_slanted_diagram_left_to_right():
    boxes = {
        "right": {"x": 400, "y": 0, "width": 100, "height": 40},  # top edge is higher
        "left": {"x": 0, "y": 15, "width": 100, "height": 40},
    }
    assert reading_order(boxes) == ["left", "right"]


def test_kind_hint():
    assert kind_hint([stroke("a", 0, 0), stroke("b", 5, 0)]) == "handwriting"
    assert kind_hint([rect("r", 0, 0), {"id": "t", "type": "arrow", "x": 0, "y": 0}]) == "diagram"
    assert kind_hint([stroke("a", 0, 0), rect("r", 0, 0)]) == "mixed"
    assert kind_hint([stroke("gone", 0, 0, isDeleted=True)]) == "handwriting"
