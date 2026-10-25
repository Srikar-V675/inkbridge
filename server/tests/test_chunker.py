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


def test_mixed_small_strokes_and_oversize_elements_stay_fast():
    small = [stroke(f"s{i}", (i % 100) * 14, (i // 100) * 60, w=10, h=10) for i in range(2900)]
    big = [rect(f"b{i}", (i % 50) * 450, 4000 + (i // 50) * 450, w=400, h=400) for i in range(2800)]
    start = time.perf_counter()
    chunks = cluster(small + big)
    assert time.perf_counter() - start < 1.0
    assert sorted(i for c in chunks for i in c) == sorted(e["id"] for e in small + big)


def test_oversize_element_still_merges_with_neighbours():
    els = [rect("huge", 0, 0, w=5000, h=5000), stroke("near", 5010, 100), stroke("far", 9000, 9000)]
    els += [stroke(f"d{i}", 9000 + i * 12, 9040) for i in range(30)]
    sets = as_sets(cluster(els))
    assert frozenset({"huge", "near"}) in sets


def test_grid_clustering_matches_brute_force_on_mixed_sizes():
    import math

    from inkbridge.chunker import clustering_elements
    from inkbridge.regions import bbox_of

    rng = random.Random(11)
    els = []
    for i in range(120):
        w, h = rng.choice([8, 15, 40, 400, 900]), rng.choice([8, 15, 40, 400, 900])
        els.append(rect(f"e{i:03}", rng.uniform(0, 2500), rng.uniform(0, 2500), w=w, h=h))
    boxes = {}
    for e in clustering_elements(els):
        b = bbox_of([e])
        boxes[e["id"]] = (b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"])
    sizes = sorted(max(b[2] - b[0], b[3] - b[1]) for b in boxes.values())
    n = len(sizes)
    median = max((sizes[n // 2] + sizes[(n - 1) // 2]) / 2, 4.0)
    threshold = 1.5 * median
    parent = {i: i for i in boxes}

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for a in boxes:
        for b in boxes:
            gx = max(boxes[a][0] - boxes[b][2], boxes[b][0] - boxes[a][2], 0)
            gy = max(boxes[a][1] - boxes[b][3], boxes[b][1] - boxes[a][3], 0)
            if a < b and math.hypot(gx, gy) < threshold:
                parent[find(a)] = find(b)
    expected = {}
    for i in boxes:
        expected.setdefault(find(i), set()).add(i)
    assert as_sets(cluster(els)) == {frozenset(v) for v in expected.values()}


def _label(i, container, x=5000, y=5000):
    return {
        "id": i,
        "type": "text",
        "x": x,
        "y": y,
        "width": 20,
        "height": 20,
        "containerId": container,
    }


def test_label_of_a_draft_or_deleted_container_is_not_content():
    els = [
        rect("draft", 0, 0, customData={"author": "agent", "draft": True}),
        _label("draft-label", "draft"),
        rect("gone", 0, 0, isDeleted=True),
        _label("gone-label", "gone", x=5010),
        stroke("ink", 300, 0),
    ]
    assert cluster(els) == [["ink"]]


def test_arrow_label_does_not_cluster_by_proximity():
    arrow = {"id": "arr", "type": "arrow", "x": 0, "y": 0, "points": [[0, 0], [300, 0]]}
    els = [arrow, _label("arr-label", "arr", x=140, y=-5), stroke("near", 150, 20)]
    assert cluster(els) == [["near"]]  # the label goes with its arrow (INK-032)


def test_dangling_container_id_clusters_by_proximity():
    els = [_label("t", "missing", x=0, y=0), stroke("near", 25, 0)]
    assert cluster(els) == [["near", "t"]]


def test_an_element_named_none_does_not_capture_unbound_elements():
    els = [stroke("None", 0, 0), stroke("a", 2000, 0), stroke("b", 4000, 0)]
    assert as_sets(cluster(els)) == {frozenset({"None"}), frozenset("a"), frozenset("b")}


def test_dense_overlapping_ink_stays_fast():
    rng = random.Random(7)
    hatch = [stroke(f"h{i}", (i % 70) * 1.0, (i // 70) * 1.0) for i in range(2500)]
    pile = [stroke(f"p{i}", 1000 + rng.uniform(0, 3), rng.uniform(0, 3)) for i in range(2500)]
    start = time.perf_counter()
    chunks = cluster(hatch + pile)
    assert time.perf_counter() - start < 1.0
    assert len(chunks) == 2


def test_kind_hint_ignores_drafts():
    draft = rect("d", 0, 0, customData={"author": "agent", "draft": True})
    assert kind_hint([stroke("a", 0, 0), draft]) == "handwriting"


def test_identical_boxes_form_one_chunk_even_when_tiny():
    # Two strokes over the same spot plus a far one; the floor keeps the threshold at 6 px.
    els = [stroke("a", 0, 0, w=0, h=0), stroke("b", 0, 0, w=0, h=0), stroke("far", 50, 0)]
    assert as_sets(cluster(els)) == {frozenset("ab"), frozenset({"far"})}
