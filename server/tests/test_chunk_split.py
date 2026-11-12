"""Oversized chunks are cut at their widest gaps (INK-209)."""

from inkbridge.canvas.chunker.split import MAX_SIDE, split_oversized


def _stroke(i, x, y, w=40, h=30):
    return {
        "id": i,
        "type": "freedraw",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "points": [[0, 0], [w, h]],
    }


def test_far_islands_in_one_group_are_separated():
    els = [_stroke(f"a{i}", i * 50, 0) for i in range(5)]
    els += [_stroke(f"b{i}", 6000 + i * 50, 0) for i in range(5)]
    els += [_stroke(f"c{i}", 0, 6000 + i * 50) for i in range(5)]
    by_id = {e["id"]: e for e in els}
    parts = split_oversized([[e["id"] for e in els]], by_id)
    assert len(parts) == 3
    assert sorted(len(p) for p in parts) == [5, 5, 5]
    assert {i[0] for p in parts for i in p} == {"a", "b", "c"}
    assert all(len({i[0] for i in p}) == 1 for p in parts)


def test_a_group_within_the_caps_is_untouched():
    els = [_stroke(f"a{i}", i * 50, 0) for i in range(10)]
    by_id = {e["id"]: e for e in els}
    assert split_oversized([[e["id"] for e in els]], by_id) == [[e["id"] for e in els]]


def test_one_overlapping_mass_is_not_cut():
    els = [_stroke(f"a{i}", 0, 0, w=MAX_SIDE + 500, h=20) for i in range(4)]
    by_id = {e["id"]: e for e in els}
    assert len(split_oversized([[e["id"] for e in els]], by_id)) == 1


def test_every_member_lands_in_exactly_one_part():
    els = [_stroke(f"s{i}", (i % 4) * 5000, (i // 4) * 5000) for i in range(16)]
    by_id = {e["id"]: e for e in els}
    parts = split_oversized([[e["id"] for e in els]], by_id)
    flat = sorted(i for p in parts for i in p)
    assert flat == sorted(by_id)
    assert len(parts) == 16


def test_a_bridging_scribble_leaves_so_the_islands_can_separate():
    islands = [_stroke(f"a{i}", i * 50, 0) for i in range(6)]
    islands += [_stroke(f"b{i}", 7000 + i * 50, 0) for i in range(6)]
    bridge = _stroke("big", 0, 0, w=7400, h=200)
    els = islands + [bridge]
    by_id = {e["id"]: e for e in els}
    parts = split_oversized([[e["id"] for e in els]], by_id)
    assert sorted(len(p) for p in parts) == [1, 6, 6]
    assert ["big"] in parts
