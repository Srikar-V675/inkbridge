"""Stroke kinds classifier (INK-121): pure shape rules, no chunker wiring."""

import math
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
