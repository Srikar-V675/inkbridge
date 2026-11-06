"""INK-120: pure server-side raster of chunk crops and thumbnails. No I/O."""

import io
import math
import random
import sys
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from inkbridge.canvas import raster

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

BG = raster.THUMB_BG
CROP_THIN_INK = 196  # ink pixels of render_crop(stroke(width=1)) before INK-171


def img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def ink(png: bytes) -> int:
    return sum(img(png).convert("L").histogram()[:255])  # pixels darker than pure white


def stroke(i="s", x=0.0, y=0.0, n=40, pressure=None, width=4, **extra):
    el = {
        "id": i,
        "type": "freedraw",
        "x": x,
        "y": y,
        "width": n * 5,
        "height": 0,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "strokeWidth": width,
        "points": [[k * 5, 0] for k in range(n)],
    }
    if pressure is not None:
        el["pressures"] = [pressure] * n
    el.update(extra)
    return el


def shape(kind, i="r", x=0, y=0, w=100, h=60, **extra):
    el = {
        "id": i,
        "type": kind,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "strokeWidth": 2,
    }
    el.update(extra)
    return el


def test_pressure_changes_stroke_width():
    low = raster.render_crop([stroke(pressure=0.1)])
    high = raster.render_crop([stroke(pressure=0.9)])
    assert ink(high) > 1.5 * ink(low)


def test_crop_under_300_ms_for_100_elements():
    rng = random.Random(1)
    els = []
    for k in range(100):
        pts, x, y = [], 0.0, 0.0
        for _ in range(29):
            x += rng.uniform(-3, 6)
            y += rng.uniform(-3, 3)
            pts.append([x, y])
        els.append(
            stroke(f"f{k}", x=rng.uniform(0, 900), y=rng.uniform(0, 600), n=1)
            | {"points": pts, "pressures": [rng.random() for _ in pts]}
        )
    els += [shape("rectangle", f"r{k}", x=k * 100, y=700) for k in range(3)]
    els += [
        {
            **shape("text", f"t{k}", x=k * 300, y=800),
            "text": "hello world\nline two",
            "fontSize": 20,
        }
        for k in range(2)
    ]
    best = min(_timed(els) for _ in range(3))
    assert best < 0.3
    assert img(raster.render_crop(els)).size[0] > 10


def _timed(els):
    t = time.perf_counter()
    raster.render_crop(els)
    return time.perf_counter() - t


def test_deleted_and_draft_elements_are_not_drawn():
    live = stroke("live")
    deleted = stroke("gone", y=500, isDeleted=True)
    draft = stroke("d", x=3000, y=3000, customData={"draft": True, "author": "agent"})
    alone = img(raster.render_crop([live])).size
    assert img(raster.render_crop([live, deleted, draft])).size == alone
    assert raster.render_crop([deleted, draft]) is None


def test_text_rectangle_ellipse_diamond_arrow_draw_ink():
    text = {**shape("text", "t"), "text": "Hi there", "fontSize": 20, "width": 80, "height": 25}
    for el in (text, shape("rectangle"), shape("ellipse"), shape("diamond")):
        assert ink(raster.render_crop([el])) > 20, el["type"]
    arrow = shape("arrow", "a", w=100, h=0, points=[[0, 0], [100, 0]], endArrowhead=None)
    headed = {**arrow, "endArrowhead": "arrow"}
    assert ink(raster.render_crop([headed])) > ink(raster.render_crop([arrow]))


def test_long_side_is_capped_and_small_ink_is_not_upscaled():
    wide = shape("line", "l", w=6000, h=0, points=[[0, 0], [6000, 0]])
    assert img(raster.render_crop([wide])).size[0] == 2048
    assert img(raster.render_crop([shape("rectangle", w=50, h=20)])).size == (70, 40)


def test_rotation_moves_the_ink():
    flat = img(raster.render_crop([shape("rectangle", w=200, h=50)])).size
    turned = img(raster.render_crop([shape("rectangle", w=200, h=50, angle=math.pi / 2)])).size
    assert flat[0] > flat[1]
    assert abs(turned[0] - flat[1]) <= 2 and abs(turned[1] - flat[0]) <= 2


def inked_box(png: bytes):
    """Bounding box of the pixels that differ from the thumbnail background, or None."""
    im = img(png)
    return ImageChops.difference(im, Image.new("RGB", im.size, BG)).getbbox()


def cluster(cols=8, rows=4, dx=140, dy=160):
    """A grid of small rectangles; the default spans about 1000 x 600 units."""
    return [
        shape("rectangle", f"c{r}-{c}", x=c * dx, y=r * dy, w=40, h=100)
        for r in range(rows)
        for c in range(cols)
    ]


def test_thumbnail_is_fitted_and_empty_canvas_is_blank():
    els = [shape("rectangle", w=2000, h=500)]
    thumb = img(raster.render_thumbnail(els))
    assert thumb.size == (960, 640)
    box = inked_box(raster.render_thumbnail(els))
    w, h = box[2] - box[0], box[3] - box[1]
    assert w <= 960 and h <= 640 and abs(w / h - 4.0) < 0.2
    assert inked_box(raster.render_thumbnail([])) is None
    draft = stroke("d", customData={"draft": True})
    assert inked_box(raster.render_thumbnail([draft])) is None


def test_thumbnail_is_960x640_on_the_panel_colour():
    assert raster.THUMB_BG == (234, 228, 215)
    draft = stroke("d", customData={"draft": True})
    for els in ([], [draft]):
        im = img(raster.render_thumbnail(els))
        assert im.size == (960, 640)
        assert im.getcolors() == [(960 * 640, BG)]


def test_thumbnail_far_outlier_does_not_shrink_the_cluster():
    base = cluster()
    far = shape("rectangle", "far", x=200000, y=200000, w=10, h=10)
    without = inked_box(raster.render_thumbnail(base))
    with_far = inked_box(raster.render_thumbnail([*base, far]))
    assert with_far[2] - with_far[0] > 0.8 * 960
    assert all(abs(a - b) <= 3 for a, b in zip(with_far, without, strict=True))


def test_thumbnail_keeps_a_near_neighbour():
    base = cluster(cols=4, rows=2, dx=100, dy=100)  # about 340 x 200 units: drawn at 2 px a unit
    near = shape("rectangle", "near", x=340 + 300, y=0, w=40, h=100)  # 300 units from the edge
    without = inked_box(raster.render_thumbnail(base))
    with_near = inked_box(raster.render_thumbnail([*base, near]))
    assert with_near[2] - with_near[0] > without[2] - without[0] + 100


def block(n_cols, n_rows, x0, prefix):
    return [
        shape("rectangle", f"{prefix}{r}-{c}", x=x0 + c * 60, y=r * 50, w=30, h=40)
        for r in range(n_rows)
        for c in range(n_cols)
    ]


@pytest.mark.parametrize(
    ("second", "x0"),
    [((3, 4), 3000), ((3, 2), 600)],  # 12 and 6 elements against a main cluster of 48
    ids=["12-vs-48-far", "6-vs-48-near"],
)
def test_thumbnail_keeps_a_second_real_cluster(second, x0):
    main = block(4, 12, 0, "m")  # 48 rectangles, about 220 x 600 units
    other = block(*second, x0, "o")
    alone = inked_box(raster.render_thumbnail(main))
    both = inked_box(raster.render_thumbnail([*main, *other]))
    assert both[2] - both[0] > 1.5 * (alone[2] - alone[0])  # the page grew to include it


def test_thumbnail_a_lone_stray_beside_a_tiny_sketch_still_drops():
    sketch = [shape("rectangle", f"s{k}", x=k * 120, w=100, h=100) for k in range(7)]
    stray = shape("rectangle", "far", x=90000, y=90000, w=100, h=100)
    alone = inked_box(raster.render_thumbnail(sketch))
    both = inked_box(raster.render_thumbnail([*sketch, stray]))
    assert all(abs(a - b) <= 3 for a, b in zip(both, alone, strict=True))


def test_thumbnail_non_finite_element_does_not_disturb_the_fit():
    good = cluster()
    nan = shape("rectangle", "nan", x=10, y=10, w=50, h=50, angle=float("nan"))
    inf = shape("line", "inf", w=10, h=0, points=[[0, 0], [float("inf"), 0]])
    assert raster._prims([nan, inf]) == []  # dropped before they reach the fit or the painter
    alone = inked_box(raster.render_thumbnail(good))
    both = inked_box(raster.render_thumbnail([*good, nan, inf]))
    assert both == alone


def test_thumbnail_minimum_stroke_width():
    line = shape("line", "l", w=1000, h=0, points=[[0, 0], [1000, 0]], strokeWidth=1)
    free = stroke("f", n=200, width=1) | {
        "points": [[k * 5, 0] for k in range(200)],
        "pressures": [0.5] * 200,
    }

    def column(els):
        im = img(raster.render_thumbnail(els))
        return sum(1 for y in range(im.size[1]) if im.getpixel((480, y)) != BG)

    n_line, n_free = column([line]), column([free])
    assert n_line >= 4
    assert n_free >= 5 and n_free > n_line


def test_thumbnail_tiny_text_is_a_bar_not_glyphs(monkeypatch):
    big = shape("rectangle", "big", w=6000, h=3000)
    text = {**shape("text", "t", x=2000, y=1000, w=200, h=25), "text": "tiny words", "fontSize": 20}
    monkeypatch.setattr(
        raster, "_font", lambda size: (_ for _ in ()).throw(AssertionError("glyph font used"))
    )
    with_text = raster.render_thumbnail([big, text])
    monkeypatch.undo()
    assert ink_diff(with_text, raster.render_thumbnail([big])) > 0


def ink_diff(a: bytes, b: bytes) -> int:
    d = ImageChops.difference(img(a), img(b)).convert("L")
    return sum(d.histogram()[1:])


def test_thumbnail_fixture_under_300_ms():
    import make_real_scale

    els = make_real_scale.build()
    best = float("inf")
    for _ in range(3):
        t = time.perf_counter()
        png = raster.render_thumbnail(els)
        best = min(best, time.perf_counter() - t)
    assert best < 0.3
    assert img(png).size == (960, 640) and inked_box(png) is not None


def test_crop_keeps_its_old_size_and_widths():
    assert img(raster.render_crop([stroke()])).size == (215, 21)
    assert ink(raster.render_crop([stroke(width=1)])) == CROP_THIN_INK


def test_malformed_elements_are_skipped():
    bad = [
        shape("rectangle", "z", w=0, h=0),
        {"id": "p", "type": "freedraw", "x": 0, "y": 0, "points": [[1], "x"]},
        {"id": "q", "type": "line", "x": float("nan"), "y": 0},
        "junk",
        None,
    ]
    assert raster.render_crop(bad) is None
    assert ink(raster.render_crop([*bad, shape("rectangle")])) > 0
