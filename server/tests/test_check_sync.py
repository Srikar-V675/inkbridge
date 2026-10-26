"""INK-036: check_sync reports what changed under a note, flagging only changed readings."""

import asyncio
import json
import time

import pytest

from inkbridge import db
from inkbridge.api import app
from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from inkbridge.recognition_worker import RecognitionWorker
from inkbridge.recognizer import Recognition, RecognizerTimeout
from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import PNG
from tests.test_search import recognise

URL = "/documents/default/check_sync"


def note_of(chunk):
    """What the export skill stores in a note's frontmatter for one chunk."""
    return {"id": chunk["id"], "hash": chunk["content_hash"], "reading": chunk["text_hash"]}


def read(chunk, text="hello world"):
    recognise(chunk, text)  # a gemini reading for the chunk's current content hash


def check(client, chunks, **kw):
    r = client.post(URL, json={"chunks": chunks, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def only(result, key):
    others = {k: v for k, v in result.items() if k != key and k != "new" and v}
    assert not others, f"unexpected {others}"
    return result[key]


@pytest.fixture
def canvas(client):
    c = Canvas(client, row("a", 3) + row("b", 3, y=500))
    for cid in ("a0", "b0"):
        read(c.chunk_of(cid), f"text of {cid}")
    return c


def notes(canvas, *ids):
    return [note_of(canvas.chunk_of(i)) for i in ids]


def test_unchanged_chunks_are_fresh_and_nothing_is_new(client, canvas):
    result = check(client, notes(canvas, "a0", "b0"))
    assert only(result, "fresh") == [canvas.chunk_of("a0")["id"], canvas.chunk_of("b0")["id"]]
    assert result["new"] == []
    assert set(result) == {"fresh", "fresh_after_reread", "changed", "replaced", "removed", "new"}


def test_a_moved_chunk_is_still_fresh(client, canvas):
    note = notes(canvas, "a0")
    for i in range(3):
        canvas.el(f"a{i}")["x"] += 250
        canvas.el(f"a{i}")["y"] += 40
    canvas.put()
    assert only(check(client, note), "fresh") == [note[0]["id"]]


def nudge(canvas):
    canvas.el("a1")["points"] = [[0, 0], [10, 21]]  # one stroke slightly redrawn
    canvas.put()


def test_a_nudged_stroke_with_the_same_reading_is_fresh_after_reread(client, canvas):
    note = notes(canvas, "a0")
    nudge(canvas)
    chunk = canvas.chunk_of("a0")
    assert chunk["content_hash"] != note[0]["hash"]
    read(chunk, "text of a0")  # re-read: same words
    (item,) = only(check(client, note), "fresh_after_reread")
    chunk = canvas.chunk_of("a0")
    assert item == {"id": chunk["id"], "hash": chunk["content_hash"], "reading": note[0]["reading"]}


def test_a_real_edit_is_changed_with_the_new_hash_and_reading(client, canvas):
    note = notes(canvas, "a0")
    canvas.el("a1")["points"] = [[0, 0], [40, -5]]
    canvas.put()
    read(canvas.chunk_of("a0"), "different words")
    chunk = canvas.chunk_of("a0")
    (item,) = only(check(client, note), "changed")
    assert item == {"id": chunk["id"], "hash": chunk["content_hash"], "reading": chunk["text_hash"]}
    assert item["reading"] != note[0]["reading"]


def test_whitespace_only_reading_differences_are_not_a_change(client, canvas):
    """text_hash is over the normalised reading, so a reflowed reading is not a change."""
    note = notes(canvas, "a0")
    nudge(canvas)
    read(canvas.chunk_of("a0"), "  text   of\na0 ")
    assert only(check(client, note), "fresh_after_reread")


def test_no_reading_for_new_ink_and_no_worker_is_changed_with_null_reading(client, canvas):
    note = notes(canvas, "a0")
    nudge(canvas)
    t0 = time.monotonic()
    (item,) = only(check(client, note), "changed")
    assert item["reading"] is None and item["id"] == note[0]["id"]
    assert time.monotonic() - t0 < 3, "no worker: nothing to wait for"


def test_deleting_a_chunk_is_removed(client, canvas):
    note = notes(canvas, "a0")
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    assert only(check(client, note), "removed") == [note[0]["id"]]


def test_an_unknown_id_is_removed_not_an_error(client, canvas):
    result = check(client, [{"id": "nope", "hash": "x", "reading": None}])
    assert only(result, "removed") == ["nope"]


def test_a_chunk_of_another_canvas_is_removed(client, canvas):
    other = client.post("/documents", json={"title": "Other"}).json()["id"]
    r = client.post(f"/documents/{other}/check_sync", json={"chunks": notes(canvas, "a0")}).json()
    assert r["removed"] == [canvas.chunk_of("a0")["id"]]


def test_a_split_is_replaced_by_the_higher_piece_and_the_other_piece_is_new(client):
    canvas = Canvas(client, row("e", 10))
    read(canvas.chunk_of("e0"), "ten strokes")
    note = notes(canvas, "e0")
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    top, low = canvas.chunk_of("e0"), canvas.chunk_of("e9")
    read(top, "first half")
    result = check(client, note)
    (item,) = only(result, "replaced")
    top = canvas.chunk_of("e0")
    assert item == {
        "id": note[0]["id"],
        "successor": top["id"],
        "hash": top["content_hash"],
        "reading": top["text_hash"],
    }
    assert [n["id"] for n in result["new"]] == [low["id"]]


def test_a_merge_replaces_both_chunks_with_the_merged_one_which_is_not_new(client):
    canvas = Canvas(client, row("p", 6) + row("q", 6, x=1090, start=6))
    note = notes(canvas, "p0", "q6")
    for i in range(6, 12):
        canvas.el(f"q{i}")["x"] -= 1000
    canvas.put()
    merged = canvas.chunk_of("p0")
    result = check(client, note)
    assert [(r["id"], r["successor"]) for r in only(result, "replaced")] == [
        (note[0]["id"], merged["id"]),
        (note[1]["id"], merged["id"]),
    ]
    assert result["new"] == [], "the successor is already reported; listing it as new duplicates it"


def test_replaced_follows_a_chain_of_successors_to_the_live_chunk(client):
    canvas = Canvas(client, row("e", 12))
    note = notes(canvas, "e0")
    for i in range(6, 12):  # split 6/6: e0..e5 become chunk x, the original is orphaned
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    x = canvas.chunk_of("e0")
    for i in range(3, 6):  # split x 3/3: x is orphaned in turn, e0..e2 become chunk z
        canvas.el(f"e{i}")["y"] += 200
    canvas.put()
    z = canvas.chunk_of("e0")
    assert len({note[0]["id"], x["id"], z["id"]}) == 3
    assert client.get(f"/regions/{x['id']}").json()["status"] == "orphaned"
    (item,) = check(client, note)["replaced"]
    assert item["successor"] == z["id"] and item["hash"] == z["content_hash"]


def test_a_successor_cycle_or_dead_end_is_removed(client, canvas):
    a, b = canvas.chunk_of("a0"), canvas.chunk_of("b0")
    conn = db.connect()
    try:  # corrupt data on purpose: two orphans pointing at each other
        conn.execute(
            "UPDATE regions SET status = 'orphaned', successor_of = ? WHERE id = ?",
            (b["id"], a["id"]),
        )
        conn.execute(
            "UPDATE regions SET status = 'orphaned', successor_of = ? WHERE id = ?",
            (a["id"], b["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    result = check(client, [note_of(a), note_of(b)])
    assert result["removed"] == [a["id"], b["id"]]


def test_new_chunks_are_listed_in_reading_order_with_preview(client, canvas):
    canvas.elements += row("c", 3, y=900) + row("d", 3, y=200, x=900)
    canvas.put()
    read(canvas.chunk_of("c0"), "a fresh line of text " * 6)
    new = check(client, notes(canvas, "a0", "b0"))["new"]
    c, d = canvas.chunk_of("c0"), canvas.chunk_of("d0")
    assert [n["id"] for n in new] == [d["id"], c["id"]]  # d is higher on the page
    nc = new[1]
    assert nc["hash"] == c["content_hash"] and nc["reading"] == c["text_hash"]
    assert nc["preview"].startswith("a fresh line") and len(nc["preview"]) <= 80
    assert new[0]["preview"] is None and new[0]["reading"] is None


def test_duplicate_ids_are_reported_once(client, canvas):
    note = notes(canvas, "a0")
    assert check(client, note + note)["fresh"] == [note[0]["id"]]


def test_check_sync_is_a_pure_read(client, canvas):
    nudge(canvas)
    before = snapshot(client)
    check(client, notes(canvas, "a0", "b0") + [{"id": "nope", "hash": "h", "reading": "r"}])
    assert snapshot(client) == before


def snapshot(client):
    conn = db.connect()
    try:
        return (
            [tuple(r) for r in conn.execute("SELECT * FROM scenes ORDER BY document_id")],
            [tuple(r) for r in conn.execute("SELECT * FROM regions ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM recognitions ORDER BY region_id")],
        )
    finally:
        conn.close()


def test_validation(client, canvas):
    assert client.post(URL, json={}).status_code == 422
    assert client.post(URL, json={"chunks": [{"id": "a"}]}).status_code == 422
    assert client.post(URL, json={"chunks": [], "wait_s": 31}).status_code == 422
    too_many = [{"id": str(i), "hash": "h", "reading": None} for i in range(2001)]
    assert client.post(URL, json={"chunks": too_many}).status_code == 422
    assert client.post("/documents/nope/check_sync", json={"chunks": []}).status_code == 404


# -- the bounded wait for the recognition worker ---------------------------------------------------


class Model:
    def __init__(self, text="text of a0", error=None, delay=0.0):
        self.text, self.error, self.delay = text, error, delay
        self.calls = 0

    def __call__(self, png, hint):
        self.calls += 1
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return Recognition(text=self.text, latex=None, kind="handwriting", model="fake")


@pytest.fixture
def with_worker(client):
    started = []

    def make(model, documents=("default",)):
        # poll_s and idle_s are huge: only check_sync's request can make the worker read now.
        w = RecognitionWorker(model, documents, idle_s=3600, poll_s=3600)
        w.start()
        app.state.recognition_worker = w
        started.append(w)
        return w

    yield make
    for w in started:
        w.stop()
    app.state.recognition_worker = None


def fresh_crop(client, canvas, chunk):
    r = client.put(
        f"/regions/{chunk['id']}/image",
        data={"scene_version": str(canvas.version)},
        files={"image": ("c.png", PNG, "image/png")},
    )
    assert r.status_code == 200


def test_check_sync_has_the_worker_read_the_edited_chunk_now(client, canvas, with_worker):
    note = notes(canvas, "a0", "b0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    model = Model(text="text of a0")
    with_worker(model)
    result = check(client, note, wait_s=10)
    assert [i["id"] for i in result["fresh_after_reread"]] == [note[0]["id"]]
    assert result["fresh"] == [note[1]["id"]]
    assert model.calls == 1, "only the chunk whose hash changed is read"


def test_a_recognizer_timeout_is_changed_with_null_reading_within_the_bound(
    client, canvas, with_worker
):
    note = notes(canvas, "a0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    model = Model(error=RecognizerTimeout("slow"))
    with_worker(model)
    t0 = time.monotonic()
    (item,) = only(check(client, note, wait_s=1), "changed")
    assert item["reading"] is None
    assert 0.9 <= time.monotonic() - t0 < 6
    assert model.calls == 1


def test_a_slow_model_is_cut_off_at_the_bound(client, canvas, with_worker):
    note = notes(canvas, "a0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    with_worker(Model(delay=3))
    t0 = time.monotonic()
    (item,) = only(check(client, note, wait_s=0.5), "changed")
    assert item["reading"] is None and time.monotonic() - t0 < 2.5


def test_a_canvas_not_opted_in_is_never_sent_to_the_model(client, canvas, with_worker):
    note = notes(canvas, "a0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    model = Model()
    with_worker(model, documents=("eval-only",))
    t0 = time.monotonic()
    (item,) = only(check(client, note, wait_s=10), "changed")
    assert item["reading"] is None and model.calls == 0
    assert time.monotonic() - t0 < 5, "nothing can fill the cache: no wait"


def test_a_stale_crop_is_not_read_and_not_waited_for(client, canvas, with_worker):
    note = notes(canvas, "a0")
    nudge(canvas)  # the browser has not re-exported the crop yet
    model = Model()
    with_worker(model)
    t0 = time.monotonic()
    (item,) = only(check(client, note, wait_s=10), "changed")
    assert item["reading"] is None and model.calls == 0
    assert time.monotonic() - t0 < 5, "the worker cannot read a stale crop: no wait"


def test_the_worker_request_does_not_bypass_idle_for_other_chunks(client, canvas, with_worker):
    note = notes(canvas, "a0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    canvas.elements += row("z", 3, y=1500)
    canvas.put()
    fresh_crop(client, canvas, canvas.chunk_of("z0"))
    model = Model()
    with_worker(model)
    check(client, note, wait_s=5)
    assert model.calls == 1, "z was not asked for and the canvas is not idle"


# -- MCP tool -------------------------------------------------------------------------------------


def test_mcp_check_sync_tool(client, canvas):
    server.set_client(ApiClient(client))
    try:
        note = notes(canvas, "a0") + [{"id": "gone", "hash": "h", "reading": None}]
        out = asyncio.run(server.mcp.call_tool("check_sync", {"chunks": note}))
        body = json.loads(out.content[0].text)
        assert body["fresh"] == [note[0]["id"]] and body["removed"] == ["gone"]
        assert [n["id"] for n in body["new"]] == [canvas.chunk_of("b0")["id"]]
        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        assert "check_sync" in names
    finally:
        server.set_client(None)


def test_mcp_check_sync_unknown_canvas_is_a_tool_error(client):
    from mcp.server.mcpserver.exceptions import ToolError

    server.set_client(ApiClient(client))
    try:
        with pytest.raises(ToolError, match="canvas"):
            asyncio.run(
                server.mcp.call_tool("check_sync", {"chunks": [], "document_id": "missing"})
            )
    finally:
        server.set_client(None)


def test_a_note_without_a_reading_never_matches_a_missing_reading(client, canvas):
    """Both null is not "same words": the edited chunk must surface as changed."""
    note = [{**notes(canvas, "a0")[0], "reading": None}]
    nudge(canvas)
    (item,) = only(check(client, note), "changed")
    assert item["reading"] is None


def test_a_successor_without_a_reading_is_read_before_answering(client, with_worker):
    canvas = Canvas(client, row("e", 10))
    note = notes(canvas, "e0")
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    top = canvas.chunk_of("e0")
    fresh_crop(client, canvas, top)
    model = Model(text="first half")
    with_worker(model)
    (item,) = check(client, note, wait_s=10)["replaced"]
    assert item["successor"] == top["id"] and item["reading"] == canvas.chunk_of("e0")["text_hash"]
    assert item["reading"] is not None and model.calls == 1


def test_same_ink_with_a_reading_the_note_lacks_is_changed(client):
    """Exported before recognition ran: the reading that arrives later must reach the note."""
    canvas = Canvas(client, row("a", 3))
    note = notes(canvas, "a0")
    assert note[0]["reading"] is None
    read(canvas.chunk_of("a0"), "late reading")
    (item,) = only(check(client, note), "changed")
    assert item["hash"] == note[0]["hash"] and item["reading"] == canvas.chunk_of("a0")["text_hash"]


def test_a_user_correction_of_the_same_ink_is_changed_and_wins_over_gemini(client, canvas):
    note = notes(canvas, "a0")
    recognise(canvas.chunk_of("a0"), "corrected by hand", source="user")
    (item,) = only(check(client, note), "changed")
    assert item["reading"] == canvas.chunk_of("a0")["text_hash"] != note[0]["reading"]
    assert canvas.chunk_of("a0")["source"] == "user"


def test_same_ink_whose_reading_vanished_is_still_fresh(client, canvas):
    note = notes(canvas, "a0")
    conn = db.connect()
    try:
        conn.execute("DELETE FROM recognitions")
        conn.commit()
    finally:
        conn.close()
    assert only(check(client, note), "fresh") == [note[0]["id"]]


def test_an_uneven_split_keeps_the_id_and_the_small_piece_is_new(client):
    canvas = Canvas(client, row("e", 10))
    read(canvas.chunk_of("e0"), "ten strokes")
    note = notes(canvas, "e0")
    for i in range(8, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    big, small = canvas.chunk_of("e0"), canvas.chunk_of("e9")
    assert big["id"] == note[0]["id"]
    result = check(client, note)
    assert [c["id"] for c in only(result, "changed")] == [big["id"]]
    assert [n["id"] for n in result["new"]] == [small["id"]]


def test_orphaned_chunks_are_never_new(client, canvas):
    for i in range(3):
        canvas.el(f"b{i}")["isDeleted"] = True
    canvas.put()
    assert check(client, notes(canvas, "a0"))["new"] == []


def test_a_chunk_in_backoff_is_not_waited_for(client, canvas, with_worker):
    note = notes(canvas, "a0")
    nudge(canvas)
    fresh_crop(client, canvas, canvas.chunk_of("a0"))
    model = Model(error=RecognizerTimeout("slow"))
    with_worker(model)
    check(client, note, wait_s=2)  # the call fails: a0 is in backoff now
    t0 = time.monotonic()
    (item,) = only(check(client, note, wait_s=10), "changed")
    assert item["reading"] is None and model.calls == 1
    assert time.monotonic() - t0 < 5, "nothing will be read during the backoff: no wait"
