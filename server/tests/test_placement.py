import random

from inkbridge.placement import (
    DEFAULT_FONT,
    GAP,
    MAX_FONT,
    MIN_FONT,
    Box,
    estimate_size,
    gap_for,
    margin_for,
    font_size_for,
    overlaps,
    place,
)


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


def test_with_anchor_falls_back_below_everything_when_both_sides_are_taken():
    anchor = _box(0, 0, 100, 40)
    occupied = [anchor, _box(150, 0, 100, 100), _box(0, 60, 100, 100)]
    assert place(occupied, (200, 50), anchor) == {"x": 0, "y": 160 + GAP}


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
        p = place(occupied, size, anchor)
        assert not _hits(_box(p["x"], p["y"], *size), occupied)


def test_rotated_box_covers_the_turned_shape():
    import math

    from inkbridge.placement import rotated_box

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
    assert font_size_for([300.0] * 5) == 450 and font_size_for([300.0] * 5) > 64


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
