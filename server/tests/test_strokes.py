"""Stroke kinds classifier (INK-121): pure shape rules, no chunker wiring."""

import math
import random
import time
from typing import Any

from inkbridge.canvas.strokes import _order, _reversals, analyse, classify


def pen(i: str, pts: list[tuple[float, float]], index: str | None = None) -> dict[str, Any]:
    """A freedraw from absolute points: x,y at the first point, relative points."""
    x0, y0 = pts[0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    e: dict[str, Any] = {
        "id": i,
        "type": "freedraw",
        "x": x0,
        "y": y0,
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "points": [[px - x0, py - y0] for px, py in pts],
        "isDeleted": False,
    }
    if index is not None:
        e["index"] = index
    return e


def word(i: str, x: float, y: float, size: float = 20, index: str | None = None) -> dict[str, Any]:
    """A wavy writing stroke of extent `size` starting at (x, y)."""
    pts = [(x + size * k / 7, y + (size / 4) * math.sin(k * 1.3)) for k in range(8)]
    return pen(i, pts, index)


def native(i: str, kind: str = "arrow", x: float = 0, y: float = 0) -> dict[str, Any]:
    return {
        "id": i,
        "type": kind,
        "x": x,
        "y": y,
        "width": 100,
        "height": 0,
        "points": [[0, 0], [100, 0]],
        "isDeleted": False,
    }


def field(n: int = 25, size: float = 20) -> list[dict[str, Any]]:
    """Small writing strokes in a grid far from the cases (y >= 5000)."""
    return [word(f"w{k}", 5000 + (k % 5) * 60, 5000 + (k // 5) * 60, size) for k in range(n)]


def line(i: str, x1: float, y1: float, x2: float, y2: float, n: int = 12, index=None):
    pts = [(x1 + (x2 - x1) * k / (n - 1), y1 + (y2 - y1) * k / (n - 1)) for k in range(n)]
    return pen(i, pts, index)


# --- Task 1 ---


def test_native_arrow_and_line_are_connectors():
    els = [
        native("a", "arrow"),
        native("l", "line"),
        {"id": "r", "type": "rectangle", "x": 0, "y": 0, "width": 50, "height": 50},
        {"id": "t", "type": "text", "x": 0, "y": 0, "width": 50, "height": 20, "text": "hi"},
        {**word("gone", 0, 0), "isDeleted": True},
    ]
    kinds = classify(els)
    assert kinds == {"a": "connector", "l": "connector"}


def test_draft_and_malformed_skipped():
    draft = {**word("d", 0, 0), "customData": {"draft": True}}
    bad = {"id": "bad", "type": "freedraw", "x": 0, "y": 0, "points": [["a"]]}
    kinds = classify([draft, bad, word("ok", 0, 0)])
    assert kinds == {"ok": "writing"}


def test_scale_ignores_long_strokes():
    # 14 words (20), 8 medium strokes (60), 8 long ones (400): a one-pass median over all of
    # them is 60, the writing is 20.
    words = [word(f"s{k}", 5000 + k * 30, 0, 20) for k in range(14)]
    mid = [line(f"m{k}", 0, 1000 + k * 40, 60, 1000 + k * 40) for k in range(8)]
    long = [line(f"l{k}", 0, 3000 + k * 40, 400, 3000 + k * 40) for k in range(8)]
    els = words + mid + long
    assert abs(analyse(els).scale - 20.0) <= 1.0
    # a long stroke more or less does not move T
    result = analyse([*els, line("forty", 0, -500, 40, -500)])
    assert abs(result.scale - 20.0) <= 1.0


def test_draw_order_uses_fractional_index():
    assert _order(["a1", "a0", None]) == [1, 0, 2]


def test_empty_and_single():
    assert classify([]) == {}
    assert analyse([]).scale == 0.0
    assert classify([word("one", 0, 0)]) == {"one": "writing"}


# --- Task 2 ---


def circle(i: str, cx: float, cy: float, r: float, n: int = 36, index=None):
    """A hand-drawn closed loop: the ends stop 5 units apart."""
    sweep = 2 * math.pi - 5 / r
    pts = [
        (cx + r * math.cos(sweep * k / (n - 1)), cy + r * math.sin(sweep * k / (n - 1)))
        for k in range(n)
    ]
    return pen(i, pts, index)


def test_container_contains_ink():
    els = [circle("c", 0, 0, 60), word("inner", -10, 0), *field()]
    kinds = classify(els)
    assert kinds["c"] == "container"
    assert kinds["inner"] == "writing"


def test_closed_loop_with_nothing_inside_is_writing():
    # a looping cursive word read as a container
    kinds = classify([circle("c", 0, 0, 60), *field(20)])
    assert kinds["c"] == "writing"


def test_centre_in_bbox_but_outside_polygon_is_not_contained():
    # A crescent open to the right: the hollow is inside its bbox but outside the curve.
    def at(r, deg):
        a = math.radians(deg)
        return (r * math.cos(a), r * math.sin(a))

    outer = [at(60, 45 + 270 * k / 20) for k in range(21)]
    inner = [at(40, 315 - 270 * k / 20) for k in range(21)]
    crescent = pen("moon", [*outer, *inner, outer[0]])
    kinds = classify([crescent, word("hollow", -10, 0), *field()])
    assert kinds["moon"] == "writing"


def test_smaller_only():
    # Each loop's centre lies inside the other loop; only the outer holds smaller ink.
    kinds = classify([circle("outer", 0, 0, 60), circle("inner", 0, 0, 30), *field()])
    assert kinds["outer"] == "container"
    assert kinds["inner"] == "writing"


def test_scribble():
    zig = [(40 * (k % 2), 30 * k / 12) for k in range(13)]
    kinds = classify([pen("z", zig), *field()])
    assert kinds["z"] == "scribble"


def test_cursive_word_is_not_scribble():
    a, b = 4.0, 8.0
    pts = [(a * t - b * math.sin(t), -b * math.cos(t)) for t in (k * 0.25 for k in range(56))]
    pts = [(x + 100, y + 100) for x, y in pts]
    stroke = pen("cursive", pts)
    d = math.hypot(*[max(c) - min(c) for c in zip(*pts, strict=True)])
    assert _reversals(pts, d) < 6
    assert classify([stroke, *field()])["cursive"] == "writing"


# --- Task 3 ---


def vee(i: str, x: float, y: float, index=None):
    """A small arrow head (extent 10) with its tip at (x + 10, y)."""
    return pen(i, [(x, y - 4), (x + 10, y), (x, y + 4)], index)


def test_straight_long_stroke_is_connector():
    els = [
        line("s", 0, 0, 200, 40, index="a0"),
        vee("vs", 190, 40, "a1"),
        line("forty", 0, 500, 40, 500, index="a2"),
        vee("vf", 30, 500, "a3"),
        *field(),
    ]
    result = analyse(els)
    assert result.kinds["s"] == "connector"
    assert result.kinds["forty"] == "connector"
    assert result.head_of == {"vs": "s", "vf": "forty"}


def test_arrow_with_separate_head():
    els = [line("s", 0, 0, 200, 40, index="a0"), vee("v", 190, 40, "a1"), *field()]
    result = analyse(els)
    assert result.kinds["s"] == "connector"
    assert result.kinds["v"] == "head"
    assert result.head_of == {"v": "s"}


def test_flat_arrow_with_separate_head_is_not_underline():
    # writing directly above a flat arrow, and a V at its end: heads are decided first
    els = [
        line("s", 0, 0, 200, 0, index="a0"),
        vee("v", 190, 0, "a1"),
        word("above", 80, -12, index="a2"),
        *field(),
    ]
    result = analyse(els)
    assert result.kinds["s"] == "connector"
    assert result.kinds["v"] == "head"
    assert result.kinds["above"] == "writing"


def test_flat_stroke_under_writing_is_underline():
    flat = line("u", 0, 0, 200, 0)
    near = classify([flat, word("above", 80, -12), *field()])
    assert near["u"] == "underline"
    flat = line("u", 0, 0, 200, 0, index="a0")  # a head makes it a connector, not bare writing
    far = classify([flat, vee("v", 190, 0, "a1"), word("above", 80, -100), *field()])
    assert far["u"] == "connector"


def test_hook_connector():
    # shaft plus a trailing barb back toward the start
    hooked = pen("h", [(0, 0), (100, 0), (200, 0), (188, -10)])
    # out 100 and back 70: the return is more than 0.4 of the path and not straight
    loops = pen("w", [(0, 600), (100, 600), (30, 620)])
    result = analyse([hooked, loops, *field()])
    assert result.kinds["h"] == "connector"
    assert result.kinds["w"] == "writing"
    assert result.head_of == {}


def test_head_must_be_next_in_draw_order():
    filler = [word(f"f{k}", 1000 + k * 40, 0, index=f"a{k + 1}") for k in range(5)]
    far = [line("s", 0, 0, 200, 40, index="a0"), *filler, vee("v", 190, 40, "a6"), *field()]
    assert classify(far)["v"] == "writing"
    # the list order is shuffled, the index order is adjacent
    near = [vee("v", 190, 40, "a1"), *field(), line("s", 0, 0, 200, 40, index="a0")]
    assert classify(near)["v"] == "head"


def test_head_must_be_in_reach():
    els = [line("s", 0, 0, 200, 0, index="a0"), vee("v", 260, 0, "a1"), *field()]
    result = analyse(els)
    assert result.kinds["v"] == "writing"
    assert result.head_of == {}


def test_head_claimed_once():
    els = [
        line("s1", 0, 0, 200, 0, index="a0"),
        line("s2", 420, 0, 220, 0, index="a1"),
        vee("v", 205, 0, "a2"),
        {"id": "box", "type": "rectangle", "x": 420, "y": -20, "width": 40, "height": 40},
        *field(),
    ]
    result = analyse(els)
    assert result.head_of == {"v": "s1"}
    assert result.kinds["s2"] == "connector"


def test_heads_are_not_writing_for_scale():
    els = field(40)
    for k in range(14):
        els += [
            line(f"s{k}", 0, k * 60, 200, k * 60, index=f"b{2 * k:03d}"),
            vee(f"v{k}", 190, k * 60, f"b{2 * k + 1:03d}"),
        ]
    result = analyse(els)
    assert abs(result.scale - 20.0) <= 1.0
    assert len(result.head_of) == 14


def test_short_flat_underline():
    under = classify([line("u", 0, 0, 24, 0), word("above", 2, -12), *field()])
    assert under["u"] == "underline"
    hyphen = classify([line("hy", 0, 0, 8, 0), word("above", 0, -12), *field()])
    assert hyphen["hy"] == "writing"


def test_native_text_counts_as_writing_above():
    text = {"id": "t", "type": "text", "x": 10, "y": -25, "width": 40, "height": 20, "text": "hi"}
    kinds = classify([line("u", 0, 0, 60, 0), text, *field()])
    assert kinds["u"] == "underline"


# --- Task 4 ---


def page_of_824() -> list[dict[str, Any]]:
    rng = random.Random(7)
    els: list[dict[str, Any]] = []
    cell = [0]

    def spot() -> tuple[float, float]:
        k = cell[0]
        cell[0] += 1
        return (k % 8) * 500.0, (k // 8) * 500.0

    for k in range(12):  # containers, each with two words inside
        x, y = spot()
        els += [
            circle(f"c{k}", x, y, 60),
            word(f"ca{k}", x - 20, y - 15),
            word(f"cb{k}", x - 10, y + 15),
        ]
    for k in range(14):  # shafts with their heads
        x, y = spot()
        ye = y + rng.uniform(-30, 30)
        els += [line(f"s{k}", x, y, x + 200, ye), vee(f"v{k}", x + 190, ye, None)]
    for k in range(20):  # underlines with writing above
        x, y = spot()
        els += [line(f"u{k}", x, y, x + 60, y), word(f"ua{k}", x + 20, y - 12)]
    for k in range(10):  # scribbles
        x, y = spot()
        els.append(pen(f"z{k}", [(x + 40 * (j % 2), y + 30 * j / 12) for j in range(13)]))
    for k in range(4):
        els.append(native(f"n{k}", "arrow", *spot()))
    for k in range(680):  # writing
        els.append(word(f"w{k}", 6000 + (k % 40) * 60, (k // 40) * 60 + rng.uniform(-3, 3)))
    while len(els) < 824:
        x, y = spot()
        if len(els) % 2:
            els.append(
                {
                    "id": f"r{len(els)}",
                    "type": "rectangle",
                    "x": x,
                    "y": y,
                    "width": 80,
                    "height": 50,
                }
            )
        else:
            els.append(
                {
                    "id": f"t{len(els)}",
                    "type": "text",
                    "x": x,
                    "y": y,
                    "width": 80,
                    "height": 20,
                    "text": "note",
                }
            )
    return els


def test_runs_under_20ms_for_824_elements():
    els = page_of_824()
    assert len(els) == 824
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        kinds = classify(els)
        times.append(time.perf_counter() - t0)
    assert min(times) < 0.020
    counts = {
        k: list(kinds.values()).count(k)
        for k in ("container", "connector", "head", "underline", "scribble")
    }
    assert counts == {"container": 12, "connector": 18, "head": 14, "underline": 20, "scribble": 10}


def test_bare_long_smooth_stroke_is_connector():
    # INK-203 (was INK-195 "bare straight dash is writing"): long and smooth is an arrow shaft
    els = [line("dash", 0, 0, 400, 0, index="z"), *field(30)]
    assert analyse(els).kinds["dash"] == "connector"


def test_gently_curved_long_stroke_is_connector():
    pts = [
        (300 * math.sin(math.pi / 2 * k / 30), 300 * (1 - math.cos(math.pi / 2 * k / 30)))
        for k in range(31)
    ]
    els = [pen("arc", pts, "z"), *field(30)]
    assert analyse(els).kinds["arc"] == "connector"


def cursive(i: str, x: float, y: float, length: float = 400, periods: int = 8):
    n = periods * 12
    pts = [
        (x + length * k / n, y + 12 * math.sin(2 * math.pi * periods * k / n)) for k in range(n + 1)
    ]
    return pen(i, pts, "z")


def test_long_cursive_word_is_writing():
    els = [cursive("cur", 0, 0), *field(30)]
    assert analyse(els).kinds["cur"] == "writing"


def test_short_smooth_stroke_is_writing():
    els = [line("short", 0, 0, 60, 0, index="z"), *field(30)]
    assert analyse(els).kinds["short"] == "writing"


def test_straight_stroke_touching_a_shape_is_connector():
    box = {
        "id": "r",
        "type": "rectangle",
        "x": -40,
        "y": -20,
        "width": 40 - 4,
        "height": 40,
        "isDeleted": False,
    }
    els = [box, line("dash", 0, 0, 4 * 20, 0, index="z"), *field(30)]
    assert analyse(els).kinds["dash"] == "connector"
