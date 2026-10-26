"""INK-014: background recognition per chunk, cached by (region, content_hash). No network: fake model."""

import sqlite3
import threading
import time

import pytest

from inkbridge import db
from inkbridge.recognition_worker import RecognitionWorker
from inkbridge.recognizer import (
    BadResponse,
    MissingApiKey,
    RateLimited,
    Recognition,
)
from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import PNG
from tests.test_search import recognise, search

LATER = 10**10  # far past any idle delay


class FakeModel:
    def __init__(self, text="x squared", latex="x^2", kind="equation", errors=()):
        self.text, self.latex, self.kind = text, latex, kind
        self.errors = list(errors)
        self.calls: list[bytes] = []

    def __call__(self, png: bytes, hint: str | None) -> Recognition:
        self.calls.append(png)
        if self.errors:
            raise self.errors.pop(0)
        return Recognition(text=self.text, latex=self.latex, kind=self.kind, model="fake-1")


def worker(model, documents=("default",), clock=lambda: LATER, **kw):
    return RecognitionWorker(model, documents, clock=clock, **kw)


def upload(client, canvas, rid):
    r = client.put(
        f"/regions/{rid}/image",
        data={"scene_version": str(canvas.version)},
        files={"image": ("c.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text


def fresh_canvas(client, *rows):
    """A canvas whose chunks all have a fresh crop, as the browser leaves it (INK-057)."""
    canvas = Canvas(client, [s for r in rows for s in r] if rows else row("a", 3))
    for c in canvas.chunks("active"):
        upload(client, canvas, c["id"])
    return canvas


def test_reads_a_fresh_chunk_and_a_second_run_makes_zero_calls(client):
    canvas = fresh_canvas(client)
    model = FakeModel()
    w = worker(model)
    assert w.run_once() == 1
    chunk = canvas.chunk_of("a0")
    assert (chunk["text"], chunk["latex"], chunk["source"]) == ("x squared", "x^2", "gemini")
    assert chunk["text_hash"] and chunk["kind"] == "equation"
    assert model.calls == [PNG]
    assert w.run_once() == 0 and worker(model).run_once() == 0  # also a fresh worker (restart)
    assert len(model.calls) == 1
    assert [h["region_id"] for h in search(client, "squared")] == [chunk["id"]]


def test_moved_chunk_makes_zero_calls_and_edited_chunk_makes_one(client):
    canvas = fresh_canvas(client)
    model = FakeModel()
    w = worker(model)
    w.run_once()
    rid = canvas.chunk_of("a0")["id"]
    for e in canvas.elements:  # move the whole chunk
        e["x"] += 300
        e["y"] += 40
    canvas.put()
    upload(client, canvas, rid)
    assert w.run_once() == 0
    assert canvas.chunk_of("a0")["text"] == "x squared"  # the reading follows the moved ink
    canvas.elements[0]["points"] = [[0, 0], [7, 9]]  # edit the ink
    canvas.put()
    upload(client, canvas, rid)
    assert w.run_once() == 1
    assert len(model.calls) == 2


def test_precedence_user_over_agent_over_gemini(client):
    canvas = fresh_canvas(client)
    worker(FakeModel(text="gemini says")).run_once()
    chunk = canvas.chunk_of("a0")
    assert chunk["source"] == "gemini"
    recognise(chunk, "agent says", source="agent")
    assert (canvas.chunk_of("a0")["text"], canvas.chunk_of("a0")["source"]) == (
        "agent says",
        "agent",
    )
    recognise(chunk, "user says", source="user")
    assert canvas.chunk_of("a0")["text"] == "user says"
    worker(FakeModel(text="gemini again")).run_once()  # nothing to do: the hash has readings
    assert canvas.chunk_of("a0")["text"] == "user says"


def test_a_user_or_agent_reading_means_no_model_call(client):
    canvas = fresh_canvas(client)
    recognise(canvas.chunk_of("a0"), "mine", source="user")
    model = FakeModel()
    assert worker(model).run_once() == 0 and model.calls == []


def test_a_stale_crop_is_skipped_until_it_is_refreshed(client):
    """The old crop file still exists, but it shows the ink before the edit: never read it."""
    canvas = fresh_canvas(client)
    canvas.elements[0]["points"] = [[0, 0], [7, 9]]  # new ink, crop not re-exported yet
    canvas.put()
    chunk = canvas.chunk_of("a0")
    assert chunk["png_stale"] is True
    model = FakeModel()
    w = worker(model)
    assert w.run_once() == 0 and model.calls == []
    upload(client, canvas, chunk["id"])
    assert w.run_once() == 1


def test_a_chunk_without_any_crop_file_is_skipped(client):
    canvas = Canvas(client, row("a", 3))  # the browser has not uploaded anything yet
    model = FakeModel()
    assert worker(model).run_once() == 0 and model.calls == []
    upload(client, canvas, canvas.chunk_of("a0")["id"])
    assert worker(model).run_once() == 1


def test_waits_until_the_canvas_has_been_idle(client):
    fresh_canvas(client)
    model = FakeModel()
    now = time.time()
    assert worker(model, clock=lambda: now, idle_s=5).run_once() == 0, "just saved: still editing"
    assert worker(model, clock=lambda: now + 6, idle_s=5).run_once() == 1


def test_only_listed_canvases_are_ever_sent_to_the_model(client):
    """Privacy: the free tier trains on content, so only opted-in (test/eval) canvases are read."""
    fresh_canvas(client)
    model = FakeModel()
    assert worker(model, documents=()).run_once() == 0
    assert worker(model, documents=("eval-page",)).run_once() == 0
    assert model.calls == []


def test_orphaned_chunks_are_not_read(client):
    canvas = fresh_canvas(client)
    for e in canvas.elements:
        e["isDeleted"] = True
        e["version"] += 1
    canvas.put()
    model = FakeModel()
    assert worker(model).run_once() == 0


def test_failures_back_off_and_never_raise(client):
    canvas = fresh_canvas(client)
    model = FakeModel(errors=[RateLimited("429"), BadResponse("junk")])
    t = [float(LATER)]
    w = worker(model, clock=lambda: t[0], backoff_s=30, backoff_max_s=600)
    assert w.run_once() == 1  # one call made, it failed, nothing saved
    assert canvas.chunk_of("a0")["text"] is None
    t[0] += 10
    assert w.run_once() == 0, "inside the 30 s backoff"
    t[0] += 25
    assert w.run_once() == 1  # second failure: backoff doubles to 60 s
    t[0] += 50
    assert w.run_once() == 0
    t[0] += 15
    assert w.run_once() == 1
    assert canvas.chunk_of("a0")["text"] == "x squared"


def test_an_unexpected_exception_is_contained(client):
    fresh_canvas(client)
    w = worker(FakeModel(errors=[ValueError("bug")]))
    assert w.run_once() == 1  # logged and backed off, not raised
    assert not w.stopped


def test_a_permanent_error_stops_the_worker(client):
    fresh_canvas(client, row("a", 3), row("b", 3, y=500))
    model = FakeModel(errors=[MissingApiKey("no key")])
    w = worker(model)
    assert w.run_once() == 1 and w.stopped
    assert w.run_once() == 0 and len(model.calls) == 1, "no further calls once stopped"


def test_kind_is_only_taken_for_auto_chunks_of_the_same_ink(client):
    canvas = fresh_canvas(client)
    worker(FakeModel(kind="diagram")).run_once()
    assert canvas.chunk_of("a0")["kind"] == "diagram"


def test_publishes_chunks_updated_after_a_reading(client):
    canvas = fresh_canvas(client)
    sent = []
    worker(FakeModel(), publish=lambda doc, msg: sent.append((doc, msg))).run_once()
    ((doc, msg),) = sent
    assert doc == "default" and msg["type"] == "chunks.updated"
    assert msg["recognized"] == [canvas.chunk_of("a0")["id"]]
    assert msg["version"] == canvas.version and msg["stale_crops"] == []


def test_drawing_is_never_blocked_while_the_model_runs(client):
    """The worker thread waits on a slow model; scene saves keep going at normal speed."""
    canvas = fresh_canvas(client)
    entered, release = threading.Event(), threading.Event()

    class SlowModel(FakeModel):
        def __call__(self, png, hint):
            entered.set()
            release.wait(10)
            return super().__call__(png, hint)

    w = worker(SlowModel(), poll_s=0.01)
    w.start()
    try:
        assert entered.wait(5)
        t0 = time.monotonic()
        for i in range(5):
            canvas.elements.append(row("z", 1, y=900 + 50 * i, start=i)[0])
            canvas.put()  # asserts 200
        assert time.monotonic() - t0 < 2.0
    finally:
        release.set()
        w.stop()
    assert not w.is_alive()


def test_the_thread_survives_and_stops_cleanly(client):
    fresh_canvas(client)
    model = FakeModel()
    w = worker(model, poll_s=0.01)
    w.start()
    deadline = time.monotonic() + 5
    while not model.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    w.stop()
    assert model.calls and not w.is_alive()


@pytest.mark.parametrize("value", [None, "", " , "])
def test_from_env_is_off_unless_canvases_are_listed(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", raising=False)
    else:
        monkeypatch.setenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", value)
    assert RecognitionWorker.from_env(recognizer=FakeModel()) is None


def test_from_env_reads_the_list_and_survives_a_missing_key(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", "eval-1, eval-2")
    monkeypatch.setenv("INKBRIDGE_RECOGNIZE_IDLE_S", "7")
    w = RecognitionWorker.from_env(recognizer=FakeModel())
    assert w.documents == ("eval-1", "eval-2") and w.idle_s == 7
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from inkbridge.recognizer import gemini

    monkeypatch.setattr(gemini, "_default", None)
    assert RecognitionWorker.from_env() is None  # no key: logged, API still starts


def test_api_starts_the_worker_only_when_configured(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from inkbridge import recognition_worker
    from inkbridge.api import app

    started = []
    monkeypatch.setattr(recognition_worker.RecognitionWorker, "start", lambda s: started.append(s))
    monkeypatch.setattr(recognition_worker.RecognitionWorker, "stop", lambda s: None)
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "w.db"))
    monkeypatch.delenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", raising=False)
    with TestClient(app):
        assert started == []
    monkeypatch.setenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", "default")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    from inkbridge.recognizer import gemini

    monkeypatch.setattr(gemini, "_default", None)
    monkeypatch.setattr(gemini.GeminiRecognizer, "_google_transport", lambda self, t: None)
    with TestClient(app):
        assert len(started) == 1 and started[0].documents == ("default",)


def test_worker_never_imports_the_api():
    """The API hands the worker hub.publish; the worker itself stays below the API layer."""
    import ast
    import inspect

    from inkbridge import recognition_worker

    tree = ast.parse(inspect.getsource(recognition_worker))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {
        f"{n.module}.{a.name}"
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
    }
    assert not any(m.startswith("inkbridge.api") for m in imported)


def other_png():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_ink_edited_during_another_call_is_not_read_under_its_old_hash(client):
    """The candidate list is seconds old by the time a chunk's turn comes: re-check it."""
    canvas = fresh_canvas(client, row("a", 3), row("b", 3, y=500))
    before = {c["id"]: c["content_hash"] for c in canvas.chunks("active")}
    edited = other_png()

    class EditsBoth(FakeModel):
        def __call__(self, png, hint):
            if not self.calls:  # during the first call both chunks are edited and re-cropped
                for i in ("a0", "b0"):
                    canvas.el(i)["points"] = [[0, 0], [8, 3]]
                canvas.put()
                for rid in before:
                    r = client.put(
                        f"/regions/{rid}/image",
                        data={"scene_version": str(canvas.version)},
                        files={"image": ("c.png", edited, "image/png")},
                    )
                    assert r.status_code == 200
            return super().__call__(png, hint)

    model = EditsBoth()
    w = worker(model)
    assert w.run_once() == 1, "the second chunk is skipped: its listed hash is gone"
    conn = db.connect()
    try:
        read_old = [
            rid
            for rid, h in before.items()
            if conn.execute(
                "SELECT 1 FROM recognitions WHERE region_id = ? AND content_hash = ?", (rid, h)
            ).fetchone()
        ]
    finally:
        conn.close()
    # Only the chunk read before the edit has a reading for its old hash (its bytes were old).
    assert len(read_old) == 1
    assert w.run_once() == 2 and model.calls[1:] == [edited, edited]


def test_a_locked_database_keeps_the_reading_and_does_not_call_again(client, monkeypatch):
    canvas = fresh_canvas(client)
    real = db.save_model_reading
    failures = [sqlite3.OperationalError("database is locked")]

    def flaky(*a, **kw):
        if failures:
            raise failures.pop()
        return real(*a, **kw)

    monkeypatch.setattr(db, "save_model_reading", flaky)
    model = FakeModel()
    w = worker(model)
    assert w.run_once() == 1 and canvas.chunk_of("a0")["text"] is None
    assert w.run_once() == 0, "the kept reading is saved without a new call"
    assert canvas.chunk_of("a0")["text"] == "x squared" and len(model.calls) == 1


def test_a_rate_limit_pauses_every_chunk_not_just_the_one(client):
    fresh_canvas(client, row("a", 3), row("b", 3, y=500))
    t = [float(LATER)]
    model = FakeModel(errors=[RateLimited("429")])
    w = worker(model, clock=lambda: t[0], backoff_s=30)
    assert w.run_once() == 1, "the second chunk is not tried against an exhausted quota"
    t[0] += 10
    assert w.run_once() == 0
    t[0] += 25
    assert w.run_once() == 2


def test_a_bad_reply_does_not_pause_the_other_chunks(client):
    fresh_canvas(client, row("a", 3), row("b", 3, y=500))
    model = FakeModel(errors=[BadResponse("junk")])
    assert worker(model).run_once() == 2


def test_stop_is_honoured_between_chunks(client):
    fresh_canvas(client, row("a", 3), row("b", 3, y=500))

    class StopsAfterOne(FakeModel):
        def __call__(self, png, hint):
            w.stop(timeout=0)
            return super().__call__(png, hint)

    model = StopsAfterOne()
    w = worker(model)
    assert w.run_once() == 1


def test_a_manual_region_keeps_its_creators_kind(client):
    canvas = fresh_canvas(client)
    r = client.post(
        "/documents/default/regions",
        data={"element_ids": '["a0"]', "kind": "diagram"},
        files={"image": ("c.png", PNG, "image/png")},
    ).json()
    worker(FakeModel(kind="equation")).run_once()
    assert client.get(f"/regions/{r['id']}").json()["kind"] == "diagram"
    assert client.get(f"/regions/{r['id']}").json()["source"] == "gemini"
    assert canvas.chunk_of("a0")["kind"] == "equation"


def test_kind_is_not_applied_when_the_ink_changed_meanwhile(client):
    canvas = fresh_canvas(client)
    chunk = canvas.chunk_of("a0")
    canvas.el("a0")["points"] = [[0, 0], [8, 3]]
    canvas.put()
    hinted = canvas.chunk_of("a0")["kind"]
    conn = db.connect()
    try:
        reading = Recognition(text="t", latex=None, kind="diagram", model="m")
        db.save_model_reading(conn, chunk["id"], chunk["content_hash"], reading)
    finally:
        conn.close()
    assert canvas.chunk_of("a0")["kind"] == hinted


def test_chunks_api_shows_the_reading(client):
    canvas = fresh_canvas(client)
    worker(FakeModel()).run_once()
    body = client.get("/documents/default/chunks").json()
    (c,) = [c for c in body["chunks"] if c["id"] == canvas.chunk_of("a0")["id"]]
    assert (c["text"], c["latex"], c["kind"]) == ("x squared", "x^2", "equation")


def test_from_env_never_raises(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_RECOGNIZE_DOCUMENTS", "eval-1")
    monkeypatch.setenv("INKBRIDGE_RECOGNIZE_IDLE_S", "soon")
    w = RecognitionWorker.from_env(recognizer=FakeModel())
    assert w is not None and w.idle_s == 5.0
    from inkbridge.recognizer import gemini

    def broken():
        raise ImportError("no SDK")

    monkeypatch.setattr(gemini, "default_recognizer", broken)
    assert RecognitionWorker.from_env() is None


def test_backoff_entries_of_superseded_ink_are_dropped(client):
    canvas = fresh_canvas(client)
    w = worker(FakeModel(errors=[BadResponse("junk")]))
    w.run_once()
    assert len(w._failures) == 1
    canvas.el("a0")["points"] = [[0, 0], [8, 3]]
    canvas.put()
    w.run_once()
    assert w._failures == {}
