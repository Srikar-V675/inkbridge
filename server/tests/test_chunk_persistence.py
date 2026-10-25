"""INK-031: chunks are stored as regions (created_by='auto') and keep their ids across edits."""

import copy
import time

import pytest

from inkbridge import db
from tests.test_chunker import stroke as _stroke
from tests.test_region_staleness import Scene
from tests.test_region_staleness import region as get
from tests.test_regions_api import PNG, REGIONS, SCENE, post
from tests.test_search import recognise, search


def stroke(i, x, y, **extra):
    return _stroke(i, x, y, version=1, **extra)


def row(prefix, n, x=0, y=0, start=0):
    """n strokes 15 px apart: one chunk (threshold is 1.5 * 20 px)."""
    return [stroke(f"{prefix}{i}", x + 15 * (i - start), y) for i in range(start, start + n)]


class Canvas(Scene):
    def el(self, i):
        return next(e for e in self.elements if e["id"] == i)

    def chunks(self, status=None):
        rows = self.client.get(REGIONS, params={"limit": 500, "chunks": True}).json()
        assert all(r["created_by"] == "auto" for r in rows)
        return [r for r in rows if status is None or r["status"] == status]

    def chunk_of(self, element_id):
        (c,) = [c for c in self.chunks("active") if element_id in c["element_ids"]]
        return c


def test_scene_save_creates_one_auto_chunk_per_cluster(client):
    canvas = Canvas(client, row("a", 4) + row("b", 3, y=500))
    chunks = canvas.chunks()
    assert sorted(c["element_ids"] for c in chunks) == [
        ["a0", "a1", "a2", "a3"],
        ["b0", "b1", "b2"],
    ]
    for c in chunks:
        assert c["status"] == "active" and c["kind"] == "handwriting"
        assert len(c["id"]) == 12 and c["png_stale"] is True  # no crop until the browser sends one
        assert c["successor_of"] is None
    assert canvas.chunk_of("a0")["bounds"] == {"x": 0, "y": 0, "width": 55, "height": 20}


def test_adding_a_stroke_keeps_the_id_and_changes_the_content_hash(client):
    canvas = Canvas(client, row("a", 10))
    before = canvas.chunk_of("a0")
    canvas.elements.append(stroke("a10", 150, 0))
    canvas.put()
    after = canvas.chunk_of("a10")
    assert after["id"] == before["id"]
    assert after["content_hash"] != before["content_hash"]
    assert "a10" in after["element_ids"]
    assert len(canvas.chunks()) == 1


def test_changed_content_drops_the_search_row_and_undo_brings_it_back(client):
    canvas = Canvas(client, row("a", 3))
    chunk = canvas.chunk_of("a0")
    recognise(chunk, "gradient")
    assert [h["region_id"] for h in search(client, "gradient")] == [chunk["id"]]
    canvas.elements.append(stroke("a3", 45, 0))
    canvas.put()
    assert search(client, "gradient") == []
    canvas.elements.pop()
    canvas.put()
    assert [h["region_id"] for h in search(client, "gradient")] == [chunk["id"]]


def test_split_orphans_the_old_chunk_with_successor_the_higher_piece(client):
    canvas = Canvas(client, row("e", 10))
    old = canvas.chunk_of("e0")
    for i in range(5, 10):  # move the right half down and away: 5 / 10 each side
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    left, right = canvas.chunk_of("e0"), canvas.chunk_of("e9")
    assert {left["id"], right["id"]}.isdisjoint({old["id"]})
    orphan = get(client, old["id"])
    assert orphan["status"] == "orphaned"
    assert orphan["successor_of"] == left["id"]  # equal overlap: the piece higher on the page
    assert orphan["element_ids"] == old["element_ids"]  # kept, so undo can match it


def test_merge_orphans_both_chunks_pointing_at_the_merged_one(client):
    canvas = Canvas(client, row("p", 6) + row("q", 6, x=1090, start=6))
    p, q = canvas.chunk_of("p0"), canvas.chunk_of("q6")
    for i in range(6, 12):
        canvas.el(f"q{i}")["x"] -= 1000  # now continues the p row
    canvas.put()
    merged = canvas.chunk_of("p0")
    assert merged["element_ids"] == sorted(
        [f"p{i}" for i in range(6)] + [f"q{i}" for i in range(6, 12)]
    )
    assert merged["id"] not in {p["id"], q["id"]}
    for old in (p, q):
        r = get(client, old["id"])
        assert r["status"] == "orphaned" and r["successor_of"] == merged["id"]


def test_moving_a_chunk_keeps_id_and_content_hash_and_flags_the_crop(client):
    canvas = Canvas(client, row("a", 4) + row("b", 4, y=500))
    chunk = canvas.chunk_of("a0")
    r = client.put(f"/regions/{chunk['id']}/image", files={"image": ("c.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["png_stale"] is False
    other = canvas.chunk_of("b0")
    for i in range(4):
        canvas.el(f"a{i}")["x"] += 200.25
        canvas.el(f"a{i}")["y"] += 33
    canvas.put()
    moved = canvas.chunk_of("a0")
    assert moved["id"] == chunk["id"]
    assert moved["content_hash"] == chunk["content_hash"]
    assert moved["stroke_hash"] != chunk["stroke_hash"]
    assert moved["png_stale"] is True
    assert moved["bounds"]["x"] == 200.25
    assert get(client, other["id"]) == other  # untouched chunk: row not rewritten


def test_undo_of_a_split_reactivates_the_orphaned_chunk_with_the_same_id(client):
    canvas = Canvas(client, row("e", 10))
    original = canvas.chunk_of("e0")
    saved = copy.deepcopy(canvas.elements)
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    pieces = [canvas.chunk_of("e0")["id"], canvas.chunk_of("e9")["id"]]
    canvas.elements = saved
    canvas.put()
    back = canvas.chunk_of("e0")
    assert back["id"] == original["id"]
    assert back["status"] == "active" and back["successor_of"] is None
    assert back["content_hash"] == original["content_hash"]
    for pid in pieces:
        r = get(client, pid)
        assert r["status"] == "orphaned" and r["successor_of"] == original["id"]


def test_undo_of_a_delete_reactivates_the_chunk(client):
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    chunk = canvas.chunk_of("a0")
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    gone = get(client, chunk["id"])
    assert gone["status"] == "orphaned" and gone["successor_of"] is None
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = False
    canvas.put()
    back = get(client, chunk["id"])
    assert back["status"] == "active" and back["content_hash"] == chunk["content_hash"]
    assert len(canvas.chunks("active")) == 2


def test_manual_regions_are_left_alone(client):
    canvas = Canvas(client, row("e", 10))
    r = post(client, ["e0", "e1"])
    manual = r.json()
    for i in range(5, 10):  # split the auto chunk; the manual region's ink is untouched
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    canvas.elements.append(stroke("e10", 150, 400))
    canvas.put()
    assert get(client, manual["id"]) == manual
    assert all(c["id"] != manual["id"] for c in canvas.chunks())
    assert [r["id"] for r in client.get(REGIONS).json()] == [manual["id"]]


def test_manual_regions_still_refresh_when_their_ink_changes(client):
    canvas = Canvas(client, row("e", 3))
    r = post(client, ["e0"])
    manual = r.json()
    canvas.el("e0")["points"][1] = [12, 22]
    canvas.put()
    after = get(client, manual["id"])
    assert after["created_by"] == "user" and after["png_stale"] is True
    assert after["content_hash"] != manual["content_hash"]


def test_created_by_auto_is_reserved_for_the_chunker(client):
    Canvas(client, row("e", 3))
    r = post(client, ["e0"], created_by="auto")
    assert r.status_code == 422


def test_drafts_never_become_chunks(client):
    draft = stroke("d", 20, 0, customData={"author": "agent", "draft": True})
    canvas = Canvas(client, [*row("a", 3), draft])
    assert [c["element_ids"] for c in canvas.chunks()] == [["a0", "a1", "a2"]]


def _big_scene():
    # 200 chunks of 10 strokes on a 20 x 10 grid: 2,000 elements.
    out = []
    for c in range(200):
        out += row(f"c{c}_", 10, x=(c % 20) * 400, y=(c // 20) * 200)
    return out


def test_one_stroke_edit_on_a_2000_element_scene_rehashes_one_chunk(client, monkeypatch):
    canvas = Canvas(client, _big_scene())
    assert len(canvas.chunks()) == 200
    calls = []
    real = db.stroke_hash
    monkeypatch.setattr(db, "stroke_hash", lambda els: calls.append(len(els)) or real(els))
    canvas.el("c7_3")["points"][1] = [11, 21]
    canvas.el("c7_3")["version"] = 2
    canvas.put()
    assert calls == [10]  # only the chunk holding the edited stroke was hashed


def test_scene_put_on_2000_elements_stays_fast(client):
    canvas = Canvas(client, _big_scene())
    canvas.el("c7_3")["points"][1] = [11, 21]
    start = time.perf_counter()
    canvas.put()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5, f"scene PUT took {elapsed:.2f} s"


def test_a_failure_while_chunking_rolls_back_the_whole_save(client, monkeypatch):
    canvas = Canvas(client, row("a", 3))
    before = canvas.chunks()

    def boom(*args, **kwargs):
        raise RuntimeError("chunker failed")

    canvas.elements.append(stroke("a3", 45, 0))
    with monkeypatch.context() as m:
        m.setattr(db, "_sync_chunks", boom)
        with pytest.raises(RuntimeError):
            client.put(SCENE, json={"base_version": canvas.version, "elements": canvas.elements})
    scene = client.get(SCENE).json()
    assert scene["version"] == canvas.version and len(scene["elements"]) == 3
    assert canvas.chunks() == before


def test_restart_rekeys_hashes_stored_before_integral_floats_hashed_as_ints(client):
    from inkbridge.regions import content_hash, legacy_content_hash

    canvas = Canvas(client, [stroke("f0", 0.5, 0), stroke("f1", 15.5, 0)])  # offset 15.0 (float)
    chunk = canvas.chunk_of("f0")
    els = canvas.elements
    old = legacy_content_hash(els)
    assert old != chunk["content_hash"] == content_hash(els)
    conn = db.connect()
    try:  # pretend the row and its reading were written by INK-029's hash
        conn.execute("UPDATE regions SET content_hash = ? WHERE id = ?", (old, chunk["id"]))
        conn.commit()
        recognise(chunk, "gradient", content_hash=old)
        db.init_db()
        assert get(client, chunk["id"])["content_hash"] == chunk["content_hash"]
        assert get(client, chunk["id"])["text"] == "gradient"
    finally:
        conn.close()
    for e in canvas.elements:  # a pure move keeps the reading and the search hit
        e["x"] += 100
    canvas.put()
    assert [h["region_id"] for h in search(client, "gradient")] == [chunk["id"]]
