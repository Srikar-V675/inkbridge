import random

import pytest

from inkbridge.agent.placement import (
    DEFAULT_FONT,
    GAP,
    INK_TO_FONT,
    LINE_FACTOR,
    MAX_FONT,
    MIN_FONT,
    Box,
    connectors_of,
    estimate_size,
    font_size_for,
    gap_for,
    line_pitch,
    margin_for,
    overlaps,
    place,
    view_rect,
    wrap_for,
)
from inkbridge.canvas.chunker import proximity_threshold


def _box(x, y, w, h) -> Box:
    return {"x": x, "y": y, "width": w, "height": h}


def _hits(box: Box, occupied: list[Box]) -> bool:
    return any(overlaps(box, o) for o in occupied)


def test_empty_canvas_places_at_origin():
    assert place([], (200, 50)) == {"x": 0, "y": 0}


def test_without_anchor_goes_below_the_lowest_box_at_the_left_edge():
    occupied = [_box(100, 0, 50, 50), _box(-20, 300, 10, 10), _box(400, 120, 10, 10)]
    assert place(occupied, (200, 50)) == {"x": -20, "y": 310 + GAP}


def test_with_anchor_goes_right_of_it():
    anchor = _box(0, 0, 100, 40)
    assert place([anchor], (200, 50), anchor) == {"x": 100 + GAP, "y": 0}


def test_with_anchor_goes_below_it_when_the_right_is_taken():
    anchor = _box(0, 0, 100, 40)
    right = _box(150, 0, 100, 30)
    assert place([anchor, right], (200, 50), anchor) == {"x": 0, "y": 40 + GAP}


def test_ring_order_east_first():
    anchor = _box(0, 0, 100, 40)
    assert place([anchor], (200, 50), anchor, 20) == {"x": 100 + gap_for(20), "y": 0}


def test_no_below_everything_fallback_when_space_exists():
    anchor = _box(0, 0, 100, 40)
    occupied = [anchor, _box(150, 0, 100, 100), _box(0, 60, 100, 100), _box(0, 5000, 10, 10)]
    p = place(occupied, (200, 50), anchor)
    assert p["y"] < 1000 and abs(p["x"]) < 6 * GAP + 200 and p["y"] < 6 * GAP + 200
    assert not _hits(_box(p["x"], p["y"], 200, 50), occupied)


def test_falls_back_below_everything_only_when_no_candidate():
    anchor = _box(0, 0, 100, 40)
    occupied = [anchor, _box(-5000, -5000, 10000, 10000)]
    assert place(occupied, (200, 50), anchor) == {"x": -5000, "y": 5000 + GAP}


def test_view_prefers_candidates_inside_view():
    anchor = _box(0, 0, 100, 40)
    occupied = [anchor, _box(140, -20, 300, 200), _box(-20, 60, 100, 100)]  # E and S blocked
    n_view = _box(-400, -400, 800, 400)  # only the north side
    assert place(occupied, (100, 40), anchor, 20, view=n_view)["y"] < 0
    free = place(occupied, (100, 40), anchor, 20)
    assert free["x"] < 0  # W wins on direction penalty alone (0.6 vs N 0.8)


def test_connector_crossing_is_penalised():
    anchor = _box(0, 0, 100, 40)
    seg = ((100, 20), (500, 20))  # runs through the east slot
    p = place([anchor], (100, 40), anchor, 20, connectors=[seg])
    assert p == {"x": 0, "y": 40 + gap_for(20)}


def test_ties_break_by_x_then_y_and_place_is_deterministic():
    rng = random.Random(7)
    for _ in range(50):
        occ = [
            _box(
                rng.uniform(-300, 300),
                rng.uniform(-300, 300),
                rng.uniform(5, 150),
                rng.uniform(5, 90),
            )
            for _ in range(12)
        ]
        anchor = occ[0]
        want = place(occ, (80, 30), anchor, 20)
        for _ in range(2):
            rng.shuffle(occ)
            assert place(occ, (80, 30), anchor, 20) == want


def test_line_pitch_and_font():
    rows = [(0, 250), (0, 250), (400, 250), (800, 250)]
    assert line_pitch(rows) == 400
    assert line_pitch([(0, 250), (3, 250)]) is None
    assert font_size_for([250] * 5, pitch=420) == round(LINE_FACTOR * 420)
    assert font_size_for([250] * 5, pitch=None) == round(250 * INK_TO_FONT)
    assert font_size_for([], pitch=-1) == DEFAULT_FONT


def test_fixture_font_within_band():  # INK-095 numbers: stroke height 250, pitch 420
    assert 0.7 <= font_size_for([250] * 10, pitch=420) / 250 <= 1.3


def test_wrap_chars():
    assert wrap_for(20, None) == 34
    assert wrap_for(20, {"width": 400, "zoom": 1}) == 20
    assert wrap_for(20, {"width": 4000, "zoom": 1}) == 34
    assert wrap_for(200, {"width": 400, "zoom": 1}) == 8


def test_view_rect_and_connectors():
    assert view_rect(None) is None
    assert view_rect({"x": 5, "y": 6, "width": 400, "height": 200, "zoom": 2}) == _box(
        5, 6, 200, 100
    )
    arrow = {"type": "arrow", "x": 10, "y": 10, "points": [[0, 0], [5, 5], [9, 0]]}
    assert connectors_of([arrow, {**arrow, "isDeleted": True}]) == [
        ((10, 10), (15, 15)),
        ((15, 15), (19, 10)),
    ]


def test_estimate_grows_with_text_lines_and_length():
    w1, h1 = estimate_size("write_text", {"text": "hi"})
    w2, h2 = estimate_size("write_text", {"text": "a much longer line of text\nand a second"})
    assert w2 > w1 and h2 > h1
    dw, dh = estimate_size("draw_diagram", {"mermaid": "flowchart TD\nA-->B"})
    assert dw > 0 and dh > 0


def test_placement_never_overlaps_occupied_boxes():
    rng = random.Random(41)
    for _ in range(500):
        occupied = [
            _box(
                rng.uniform(-500, 500),
                rng.uniform(-500, 500),
                rng.uniform(1, 300),
                rng.uniform(1, 300),
            )
            for _ in range(rng.randint(1, 30))
        ]
        size = (rng.uniform(10, 600), rng.uniform(10, 400))
        anchor = rng.choice(occupied) if rng.random() < 0.7 else None
        recent = rng.choice(occupied) if rng.random() < 0.5 else None
        p = place(occupied, size, anchor, recent=recent)
        assert not _hits(_box(p["x"], p["y"], *size), occupied)


def test_rotated_box_covers_the_turned_shape():
    import math

    from inkbridge.agent.placement import rotated_box

    assert rotated_box(_box(0, 0, 100, 10), 0) == _box(0, 0, 100, 10)
    r = rotated_box(_box(0, 0, 100, 10), math.pi / 2)
    assert math.isclose(r["x"], 45) and math.isclose(r["y"], -45)
    assert math.isclose(r["width"], 10) and math.isclose(r["height"], 100)
    r = rotated_box(_box(0, 0, 100, 100), math.pi / 4)
    assert math.isclose(r["width"], 100 * math.sqrt(2))


def test_font_scales_with_ink_height():
    assert font_size_for([20] * 5) < font_size_for([30] * 5)


def test_font_is_clamped():
    assert font_size_for([1] * 5) == MIN_FONT
    assert font_size_for([10_000] * 5) == MAX_FONT


def test_too_little_ink_uses_default():
    assert font_size_for([]) == DEFAULT_FONT
    assert font_size_for([30, 30]) == DEFAULT_FONT


def test_median_ignores_outliers():
    assert font_size_for([20, 20, 20, 20, 5000]) == font_size_for([20] * 5)


def test_size_hint_changes_and_clamps():
    h = [24] * 5
    assert font_size_for(h, "small") < font_size_for(h) < font_size_for(h, "large")
    assert font_size_for([1] * 5, "small") == MIN_FONT


def test_estimate_uses_payload_font_size():
    w1, h1 = estimate_size("write_text", {"text": "hello", "font_size": 20})
    w2, h2 = estimate_size("write_text", {"text": "hello", "font_size": 40})
    assert w2 == 2 * w1 and h2 == 2 * h1
    assert estimate_size("write_text", {"text": "hello"}) == (w1, h1)
    assert (
        estimate_size("draw_diagram", {"font_size": 40})[0]
        == 2 * estimate_size("draw_diagram", {})[0]
    )


def test_font_size_has_no_64_cap():
    assert font_size_for([300.0] * 5) == 300 and font_size_for([300.0] * 5) > 64


def test_font_size_scales_linearly():
    assert abs(font_size_for([30] * 5) * 10 - font_size_for([300] * 5)) <= 1


def test_gap_and_margin_scale_with_font():
    anchor = _box(0, 0, 4000, 1000)
    spot = place([anchor], (100, 100), anchor, 450)
    assert spot["x"] == anchor["width"] + gap_for(450) and gap_for(450) > GAP
    assert gap_for(28) == GAP and gap_for(20) == GAP
    near = _box(0, 0, 100, 100)
    other = _box(100 + 100, 0, 100, 100)  # 100 apart: clear at 1x margin, overlapping at 450 fs
    assert not overlaps(near, other) and overlaps(near, other, margin_for(450))


def test_estimate_wraps_long_lines():
    w, h = estimate_size("write_text", {"text": "x" * 400, "font_size": 300, "wrap_chars": 50})
    assert w == 50 * 0.6 * 300 and h == 8 * 1.25 * 300


def _stroke(eid, w, h, **extra):
    return {"id": eid, "type": "freedraw", "x": 0, "y": 0, "points": [[0, 0], [w, h]], **extra}


def test_proximity_threshold_is_k_times_median_of_live_non_draft_ink():
    els = [_stroke(f"s{i}", 30, 40) for i in range(3)]
    els.append(_stroke("d", 900, 900, customData={"draft": True}))
    els.append(_stroke("x", 900, 900, isDeleted=True))
    assert proximity_threshold(els) == pytest.approx(1.5 * 40)
    assert proximity_threshold([]) == 0.0


def test_second_op_stacks_below_recent_draft():
    anchor = _box(0, 0, 100, 40)
    d = _box(140, 0, 200, 50)
    below = _box(0, 80, 100, 50)
    far = _box(0, 5000, 10, 10)
    p = place([anchor, d, below, far], (200, 50), anchor, recent=d)
    assert abs(p["x"] - d["x"]) <= GAP
    assert p["y"] <= d["y"] + d["height"] + GAP + 50


def test_no_anchor_continues_the_column():
    d = _box(30, 100, 200, 50)
    far = _box(0, 5000, 10, 10)
    assert place([d, far], (200, 50), recent=d) == {"x": 30, "y": 100 + 50 + GAP}


@pytest.mark.parametrize("scale", [1, 10])
@pytest.mark.parametrize("anchored", [False, True])
def test_consecutive_placements_stay_close(scale, anchored):
    fs, size = 20 * scale, (200 * scale, 50 * scale)
    anchor = _box(0, 0, 100 * scale, 40 * scale)
    occupied = [anchor, _box(0, 5000 * scale, 10, 10)]
    recent, spots = None, []
    for _ in range(5):
        p = place(occupied, size, anchor if anchored else None, fs, recent=recent)
        recent = _box(p["x"], p["y"], *size)
        occupied.append(recent)
        spots.append(p)
    gap = gap_for(fs)
    bound = 5 * (size[1] + 2 * gap) + gap
    first = spots[0]
    for p in spots:
        assert ((p["x"] - first["x"]) ** 2 + (p["y"] - first["y"]) ** 2) ** 0.5 <= bound


def test_big_scene_with_view_is_bounded_and_matches_small_scene(monkeypatch):
    import time

    from inkbridge.agent import placement

    view = _box(0, 0, 4000, 3000)
    small = [_box(100, 100, 50, 50)]
    want = place(small, (200, 50), view=view)
    far = [_box(100000 + i * 60, 100000 + (i % 7) * 60, 50, 50) for i in range(4000)]
    calls = 0
    real = placement.overlaps

    def counting(*a, **k):
        nonlocal calls
        calls += 1
        return real(*a, **k)

    monkeypatch.setattr(placement, "overlaps", counting)
    t = time.perf_counter()
    assert place(small + far, (200, 50), view=view) == want
    assert calls < 200 and time.perf_counter() - t < 1
    dense = [_box(i * 60, j * 60, 50, 50) for i in range(70) for j in range(70)]
    p = place(dense, (200, 50), view=view)
    assert not any(real(_box(p["x"], p["y"], 200, 50), o) for o in dense)
