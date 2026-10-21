import io

from PIL import Image

from inkbridge.imaging import cap_width, decimate_strokes


def png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def size(data):
    return Image.open(io.BytesIO(data)).size


def test_wide_image_is_downscaled_to_cap_keeping_aspect():
    assert size(cap_width(png(2048, 512))) == (1024, 256)


def test_image_at_or_under_cap_is_returned_untouched():
    small = png(1024, 300)
    assert cap_width(small) is small
    assert size(cap_width(png(10, 10), max_width=5)) == (5, 5)


def test_extreme_aspect_ratio_never_collapses_to_zero_height():
    assert size(cap_width(png(4000, 1)))[1] == 1


def stroke(n, sid="s"):
    return {"id": sid, "points": [[i, i] for i in range(n)], "pressures": [i / n for i in range(n)]}


def total(strokes):
    return sum(len(s["points"]) for s in strokes)


def test_under_budget_is_unchanged():
    strokes = [stroke(100)]
    assert decimate_strokes(strokes, 5000) == strokes


def test_over_budget_is_decimated_within_limit_keeping_ends_and_pressure_alignment():
    (out,) = decimate_strokes([stroke(12000)], 5000)
    assert len(out["points"]) <= 5000 and len(out["points"]) == len(out["pressures"])
    assert out["points"][0] == [0, 0] and out["points"][-1] == [11999, 11999]
    # pressure stays paired with its point
    for (x, _), p in zip(out["points"], out["pressures"], strict=True):
        assert p == x / 12000


def test_many_tiny_strokes_still_respect_the_limit():
    out = decimate_strokes([stroke(2, f"s{i}") for i in range(6000)], 5000)
    assert total(out) <= 5000


def test_budget_is_shared_across_strokes():
    out = decimate_strokes([stroke(8000, "a"), stroke(8000, "b")], 5000)
    assert total(out) <= 5000 and [s["id"] for s in out] == ["a", "b"]
    assert all(len(s["points"]) >= 2 for s in out)


def test_mismatched_pressure_length_is_dropped_not_misaligned():
    s = {"id": "s", "points": [[i, i] for i in range(100)], "pressures": [0.5] * 40}
    (out,) = decimate_strokes([s], 10)
    assert len(out["points"]) == 10 and out["pressures"] == []
