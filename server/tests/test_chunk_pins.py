"""INK-059: pinned groups (manual merge/split) are hard chunk boundaries in the pure chunker."""

from inkbridge.chunker import chunk_scene
from tests.test_chunker import arrow, as_sets, rect, stroke


def row(prefix, n, x=0, y=0):
    """n strokes 15 px apart: one proximity chunk."""
    return [stroke(f"{prefix}{i}", x + 15 * i, y) for i in range(n)]


def test_without_pins_nothing_changes():
    els = row("a", 4) + row("b", 3, y=500)
    assert chunk_scene(els).chunks == chunk_scene(els, pins=[]).chunks
    assert chunk_scene(els).pinned == [False, False]


def test_a_pin_merges_far_apart_ink_into_one_chunk():
    els = row("a", 2) + row("b", 2, y=500)
    out = chunk_scene(els, pins=[["a0", "a1", "b0", "b1"]])
    assert as_sets(out.chunks) == {frozenset({"a0", "a1", "b0", "b1"})}
    assert out.pinned == [True]


def test_a_pin_splits_touching_ink_and_the_rest_stays_one_chunk():
    els = row("a", 5)
    out = chunk_scene(els, pins=[["a0", "a1"]])
    assert as_sets(out.chunks) == {frozenset({"a0", "a1"}), frozenset({"a2", "a3", "a4"})}
    flags = dict(zip(map(tuple, out.chunks), out.pinned, strict=True))
    assert flags[("a0", "a1")] is True and flags[("a2", "a3", "a4")] is False


def test_new_ink_next_to_a_pinned_chunk_does_not_join_it():
    els = row("a", 2) + [stroke("new", 30, 0)]
    out = chunk_scene(els, pins=[["a0", "a1"]])
    assert as_sets(out.chunks) == {frozenset({"a0", "a1"}), frozenset({"new"})}


def test_two_pins_never_join_each_other():
    els = row("a", 4)
    out = chunk_scene(els, pins=[["a0", "a1"], ["a2", "a3"]])
    assert as_sets(out.chunks) == {frozenset({"a0", "a1"}), frozenset({"a2", "a3"})}
    assert out.pinned == [True, True]


def test_overlapping_pins_are_made_disjoint_first_pin_wins():
    els = row("a", 3, y=0) + row("b", 1, y=500)
    out = chunk_scene(els, pins=[["a0", "a1"], ["a1", "a2", "b0"]])
    assert as_sets(out.chunks) == {frozenset({"a0", "a1"}), frozenset({"a2", "b0"})}


def test_pins_ignore_deleted_draft_unknown_and_connector_ids():
    els = [
        *row("a", 2),
        stroke("gone", 500, 0, isDeleted=True),
        stroke("draft", 520, 0, customData={"draft": True}),
        arrow("ar", 40, 0, 300),
    ]
    out = chunk_scene(els, pins=[["a0", "gone", "draft", "missing", "ar"], ["gone"]])
    # The pin keeps only a0; a1 is left to proximity, so it forms its own chunk; the empty pin vanishes.
    ink = [set(c) - {"ar"} for c in out.chunks]
    assert {"a0"} in ink and {"a1"} in ink
    assert out.pinned == [c == ["a0"] or set(c) == {"a0", "ar"} for c in out.chunks]


def test_bound_text_follows_its_pinned_container():
    label = {
        "id": "label",
        "type": "text",
        "x": 10,
        "y": 10,
        "width": 20,
        "height": 10,
        "containerId": "box",
    }
    els = [rect("box", 0, 0), label, rect("near", 110, 0)]
    out = chunk_scene(els, pins=[["box"]])
    assert as_sets(out.chunks) == {frozenset({"box", "label"}), frozenset({"near"})}


def test_a_short_arrow_into_a_pinned_chunk_links_instead_of_merging():
    els = [
        rect("a", 0, 0, 100, 100),
        rect("b", 300, 0, 100, 100),
        arrow("ar", 100, 50, 200, start="a", end="b"),
    ]
    assert as_sets(chunk_scene(els).chunks) == {frozenset({"a", "b", "ar"})}  # merges unpinned
    out = chunk_scene(els, pins=[["a"]])
    assert as_sets(out.chunks) == {frozenset({"a", "ar"}), frozenset({"b"})}
    assert len(out.links) == 1


def test_overlapping_pins_never_separate_a_label_from_its_container():
    label = {
        "id": "label",
        "type": "text",
        "x": 10,
        "y": 10,
        "width": 20,
        "height": 10,
        "containerId": "box",
    }
    els = [rect("box", 0, 0), label, rect("other", 500, 0)]
    out = chunk_scene(els, pins=[["box"], ["label", "other"]])
    assert as_sets(out.chunks) == {frozenset({"box", "label"}), frozenset({"other"})}
