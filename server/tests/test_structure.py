"""Boxes and arrows as a reader hint (INK-208)."""

from inkbridge.canvas import structure


def _rect(i, x, y, w=100, h=60):
    return {"id": i, "type": "rectangle", "x": x, "y": y, "width": w, "height": h, "angle": 0}


def _arrow(i, x, y, dx, dy):
    return {
        "id": i, "type": "arrow", "x": x, "y": y, "width": abs(dx), "height": abs(dy), "angle": 0,
        "points": [[0, 0], [dx, dy]], "endArrowhead": "arrow", "startArrowhead": None,
    }  # fmt: skip


def test_two_boxes_and_an_arrow_are_described():
    els = [_rect("a", 0, 0), _rect("b", 300, 0), _arrow("x", 100, 30, 200, 0)]
    d = structure.describe(els, {"a", "b", "x"})
    assert d is not None
    assert len(d["boxes"]) == 2 and "left" in d["boxes"][0] and "right" in d["boxes"][1]
    assert d["arrows"] == ["N1 -> N2 (arrowhead at N2)"]


def test_hint_tells_the_reader_to_trust_the_picture():
    els = [_rect("a", 0, 0), _rect("b", 300, 0), _arrow("x", 100, 30, 200, 0)]
    h = structure.hint(els, {"a", "b", "x"})
    assert h is not None and "the picture wins" in h and "label -> label" in h


def test_plain_handwriting_has_no_hint():
    words = [
        {"id": f"w{i}", "type": "freedraw", "x": i * 8, "y": 0, "width": 6, "height": 9, "angle": 0,
         "points": [[0, 0], [3, 4], [6, 9]]}
        for i in range(30)
    ]  # fmt: skip
    assert structure.hint(words, {w["id"] for w in words}) is None


def test_box_in_a_linked_chunk_is_named_as_outside():
    els = [_rect("a", 0, 0), _rect("b", 900, 0), _arrow("x", 100, 30, 800, 0)]
    d = structure.describe(els, {"a", "x"})
    assert d is not None and "outside this image" in d["boxes"][1]


def test_one_element_is_not_a_diagram():
    assert structure.hint([_rect("a", 0, 0)], {"a"}) is None
