import copy

from inkbridge.regions import bbox_of, stroke_hash

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
