import copy

from inkbridge.regions import bbox_of, content_hash, stroke_hash, text_hash

STROKE = {
    "id": "a",
    "type": "freedraw",
    "x": 10,
    "y": 20,
    "width": 30,
    "height": 40,
    "angle": 0,
    "points": [[0, 0], [5, 5], [30, 40]],
    "pressures": [0.2, 0.5, 0.9],
    "isDeleted": False,
    "version": 3,
    "versionNonce": 111,
    "updated": 1000,
    "seed": 42,
    "customData": {"x": 1},
}


def test_hash_ignores_volatile_fields():
    base = stroke_hash([STROKE])
    for field, value in [
        ("version", 99),
        ("versionNonce", 5),
        ("updated", 2000),
        ("seed", 7),
        ("customData", {"author": "agent"}),
    ]:
        changed = {**STROKE, field: value}
        assert stroke_hash([changed]) == base, field


def test_hash_changes_when_ink_changes():
    base = stroke_hash([STROKE])
    moved = copy.deepcopy(STROKE)
    moved["points"][1] = [6, 5]
    assert stroke_hash([moved]) != base
    assert stroke_hash([{**STROKE, "isDeleted": True}]) != base
    assert stroke_hash([{**STROKE, "pressures": [0.2, 0.5, 0.8]}]) != base


def test_hash_is_order_independent():
    other = {**STROKE, "id": "b", "x": 99}
    assert stroke_hash([STROKE, other]) == stroke_hash([other, STROKE])


def test_bbox_matches_hand_computed_fixture():
    a = {"id": "a", "x": 10, "y": 20, "width": 30, "height": 40}
    b = {"id": "b", "x": -5, "y": 0, "width": 10, "height": 100}
    # x: -5..40, y: 0..100
    assert bbox_of([a, b]) == {"x": -5, "y": 0, "width": 45, "height": 100}


def test_bbox_ignores_deleted_elements_unless_all_deleted():
    live = {"id": "a", "x": 0, "y": 0, "width": 10, "height": 10}
    gone = {"id": "b", "x": 500, "y": 500, "width": 10, "height": 10, "isDeleted": True}
    assert bbox_of([live, gone]) == {"x": 0, "y": 0, "width": 10, "height": 10}
    assert bbox_of([gone]) == {"x": 500, "y": 500, "width": 10, "height": 10}


def test_missing_is_deleted_hashes_like_false():
    bare = {k: v for k, v in STROKE.items() if k != "isDeleted"}
    assert stroke_hash([bare]) == stroke_hash([{**bare, "isDeleted": False}])


def test_bbox_uses_point_extents_for_strokes_drawn_left_and_up():
    # Excalidraw keeps x,y at the first point; later points may be negative.
    el = {"id": "a", "x": 100, "y": 100, "width": 50, "height": 50, "points": [[0, 0], [-50, -50]]}
    assert bbox_of([el]) == {"x": 50, "y": 50, "width": 50, "height": 50}


def test_hash_is_an_allow_list_not_a_deny_list():
    base = stroke_hash([STROKE])
    for field, value in [
        ("strokeColor", "#f00"),
        ("boundElements", [{"id": "q"}]),
        ("frameId", "f"),
    ]:
        assert stroke_hash([{**STROKE, field: value}]) == base, field


# --- content_hash / text_hash (INK-029) ---------------------------------------------------


def _moved(el, dx, dy):
    return {**el, "x": el["x"] + dx, "y": el["y"] + dy}


def test_content_hash_ignores_translation_of_all_elements():
    els = [STROKE, {**STROKE, "id": "s2", "x": 50, "y": 60}]
    assert content_hash(els) == content_hash([_moved(e, 400, -120) for e in els])


def test_content_hash_ignores_ids_and_draw_order():
    other = {**STROKE, "id": "s2", "x": 50, "y": 60}
    renamed = [{**STROKE, "id": "n1"}, {**other, "id": "n2"}]
    assert content_hash([STROKE, other]) == content_hash(renamed)
    assert content_hash([STROKE, other]) == content_hash([other, STROKE])


def test_content_hash_changes_with_ink():
    base = content_hash([STROKE])
    assert content_hash([{**STROKE, "points": [[0, 0], [1, 2], [9, 9]]}]) != base
    assert content_hash([{**STROKE, "pressures": [0.2, 0.5, 0.8]}]) != base
    other = {**STROKE, "id": "s2", "x": 500, "y": 60}
    assert content_hash([STROKE, other]) != base  # added stroke
    assert content_hash([STROKE, _moved(other, 30, 0)]) != content_hash([STROKE, other])  # shape


def test_content_hash_drops_deleted_elements_and_ignores_churn_fields():
    other = {**STROKE, "id": "s2", "x": 500, "y": 60}
    assert content_hash([STROKE, {**other, "isDeleted": True}]) == content_hash([STROKE])
    for field, value in [
        ("version", 99),
        ("versionNonce", 7),
        ("updated", 1),
        ("seed", 3),
        ("customData", {"author": "agent", "draft": False}),
    ]:
        assert content_hash([{**STROKE, field: value}]) == content_hash([STROKE]), field


def test_content_hash_of_nothing_is_stable():
    assert content_hash([]) == content_hash([{**STROKE, "isDeleted": True}])


def test_text_hash_normalises_whitespace_only():
    assert text_hash("a  b\n c ", None) == text_hash("a b c", "")
    assert text_hash("a b c", None) != text_hash("a b d", None)
    assert text_hash("x", r"\frac{1}{2}") != text_hash("x", None)
