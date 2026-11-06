"""INK-120: pure server-side raster of chunk crops and thumbnails. No I/O."""

import io
import math
import random
import time

from PIL import Image

from inkbridge.canvas import raster


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


def test_thumbnail_is_fitted_and_empty_canvas_is_blank():
    els = [shape("rectangle", w=2000, h=500)]
    thumb = img(raster.render_thumbnail(els))
    assert thumb.size == (480, 320)
    box = thumb.point(lambda v: 255 - v).getbbox()  # bounds of the non-white pixels
    w, h = box[2] - box[0], box[3] - box[1]
    assert w <= 480 and h <= 320 and abs(w / h - 4.0) < 0.2
    blank = img(raster.render_thumbnail([]))
    assert blank.size == (480, 320) and ink(raster.render_thumbnail([])) == 0
    draft = stroke("d", customData={"draft": True})
    assert ink(raster.render_thumbnail([draft])) == 0


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
