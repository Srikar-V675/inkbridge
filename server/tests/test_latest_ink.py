"""INK-202: offers from the latest ink (fake reader, never a real claude process)."""

import json

import pytest

from inkbridge import db
from inkbridge.agent import latest_ink
from inkbridge.recognizer import RecognizerError
from tests.test_chunk_persistence import Canvas, row, stroke

QUESTION = json.dumps({"text": "What is MCP?", "intent": "question"})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_RECOGNIZER", raising=False)
    latest_ink._mark.clear()
    for k in latest_ink.stats:
        latest_ink.stats[k] = 0
    monkeypatch.setattr(latest_ink, "reader", None)


class Reader:
    def __init__(self, reply=QUESTION, hook=None):
        self.reply, self.hook, self.pngs = reply, hook, []

    def __call__(self, png):
        self.pngs.append(png)
        if self.hook:
            self.hook()
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def poll():
    conn = db.connect()
    try:
        return latest_ink.poll(conn, "default")
    finally:
        conn.close()


def setup(client, monkeypatch, reader):
    monkeypatch.setattr(latest_ink, "reader", reader)
    return Canvas(client, row("a", 4))


def test_question_ink_gives_candidate(client, monkeypatch):
    r = Reader()
    canvas = setup(client, monkeypatch, r)
    (c,) = poll()
    assert c.kind == "question" and c.anchor == canvas.chunk_of("a0")["id"]
    assert c.payload["text"] == "What is MCP?" and c.payload["src"] == "latest"
    assert c.payload["prepare"] is True and len(c.payload["key"]) == 16
    assert len(r.pngs) == 1 and r.pngs[0].startswith(b"\x89PNG")


def test_equation_gives_open_equation(client, monkeypatch):
    setup(client, monkeypatch, Reader(json.dumps({"text": "2+2=", "intent": "equation"})))
    (c,) = poll()
    assert c.kind == "open_equation" and "prepare" not in c.payload


def test_none_and_half_word_give_nothing(client, monkeypatch):
    setup(client, monkeypatch, Reader(json.dumps({"text": "Mee", "intent": "none"})))
    assert poll() == []


def test_unparseable_reply_gives_nothing(client, monkeypatch):
    setup(client, monkeypatch, Reader("sure! it says hi"))
    assert poll() == []


def test_fenced_reply_is_parsed(client, monkeypatch):
    setup(client, monkeypatch, Reader(f"```json\n{QUESTION}\n```"))
    assert len(poll()) == 1


def test_only_new_strokes_sent(client, monkeypatch):
    r = Reader()
    setup(client, monkeypatch, r)
    poll()
    assert poll() == [] and len(r.pngs) == 1


def test_changed_during_call_is_dropped(client, monkeypatch):
    holder = {}

    def more():
        canvas = holder["c"]
        canvas.elements.append(stroke("b0", 0, 300))
        canvas.put()
        r.hook = None

    r = Reader(hook=more)
    holder["c"] = setup(client, monkeypatch, r)
    assert poll() == [] and latest_ink.stats["dropped"] == 1
    assert len(poll()) == 1  # the union is looked at now
    assert len(r.pngs) == 2


def test_draft_and_agent_ink_ignored(client, monkeypatch):
    r = Reader()
    monkeypatch.setattr(latest_ink, "reader", r)
    els = [
        stroke("d0", 0, 0, customData={"draft": True, "author": "agent"}),
        stroke("g0", 20, 0, customData={"author": "agent"}),
    ]
    Canvas(client, els)
    assert poll() == [] and r.pngs == []


def test_reader_error_advances_and_returns_empty(client, monkeypatch):
    r = Reader(RecognizerError("boom"))
    setup(client, monkeypatch, r)
    assert poll() == [] and latest_ink.stats["errors"] == 1
    assert poll() == [] and len(r.pngs) == 1


def test_no_reader_means_off(client):
    Canvas(client, row("a", 4))
    assert latest_ink.enabled() is False and poll() == []


# --- scan_now wiring (Task 3) ---


@pytest.fixture
def gate(monkeypatch):
    from inkbridge.agent import attention as attention_mod
    from inkbridge.api import offers as offers_api

    class Clock:
        t = 0.0

        def __call__(self):
            return self.t

    c = Clock()
    monkeypatch.setenv("INKBRIDGE_QUIET_S", "0")
    monkeypatch.setattr(attention_mod.attention, "clock", c)
    monkeypatch.setattr(offers_api, "_ARM_TIMERS", False)
    offers_api.pushed.clear()
    offers_api._seen_session.clear()
    attention_mod.attention.update("default", False)
    c.t += 1
    yield attention_mod.attention
    attention_mod.attention.forget("default")


def offers_of(client):
    return client.get("/documents/default/offers").json()["offers"]


def test_scan_now_creates_one_offer_with_text(client, monkeypatch, gate):
    from inkbridge.api import offers as offers_api

    canvas = setup(client, monkeypatch, Reader())
    offers_api.scan_now("default")
    (o,) = offers_of(client)
    assert o["kind"] == "question" and o["payload"]["text"] == "What is MCP?"
    assert o["anchor_chunk"] == canvas.chunk_of("a0")["id"]


def test_closed_gate_makes_no_call(client, monkeypatch, gate):
    from inkbridge.api import offers as offers_api

    r = Reader()
    setup(client, monkeypatch, r)
    gate.update("default", True)
    offers_api.scan_now("default")
    assert r.pngs == [] and offers_of(client) == []


def test_open_offer_blocks_latest(client, monkeypatch, gate):
    from inkbridge.api import offers as offers_api

    r = Reader()
    canvas = setup(client, monkeypatch, r)
    cid = canvas.chunk_of("a0")["id"]
    body = {"kind": "related", "anchor_chunk": cid, "reason": "why", "score": 0.5}
    assert client.post("/documents/default/offers", json=body).status_code == 201
    offers_api.scan_now("default")
    assert r.pngs == []
    assert "default" not in latest_ink._mark or latest_ink._mark["default"] < db_head()


def db_head():
    conn = db.connect()
    try:
        return db.scene_version(conn, "default")
    finally:
        conn.close()


def test_fallback_skipped_after_latest(client, monkeypatch, gate):
    from inkbridge.agent import detectors
    from tests.test_detectors import age
    from tests.test_search import recognise

    canvas = setup(client, monkeypatch, Reader())
    canvas.elements.extend(row("b", 3, y=500))
    canvas.put()
    a, b = canvas.chunk_of("a0"), canvas.chunk_of("b0")
    for c in (a, b):
        recognise(c, "What is MCP?")
    age()
    conn = db.connect()
    try:
        extra = latest_ink.poll(conn, "default")
        assert [c.anchor for c in extra] == [a["id"]] or [c.anchor for c in extra] == [b["id"]]
        detectors.run(conn, "default", extra=extra)
        (o,) = [o for o in offers_of(client)]
        conn.execute("UPDATE offers SET status='dismissed' WHERE id=?", (o["id"],))
        conn.commit()
        detectors.run(conn, "default")
        kinds = [(x["anchor_chunk"], x["kind"]) for x in offers_of(client)]
    finally:
        conn.close()
    assert kinds.count((o["anchor_chunk"], "question")) == 1  # no second one on the same anchor
    other = b["id"] if o["anchor_chunk"] == a["id"] else a["id"]
    assert (other, "question") in kinds  # a different chunk can still get one


def test_fallback_still_works_without_reader(client, gate):
    from inkbridge.api import offers as offers_api
    from tests.test_detectors import chunks

    chunks(client, "Why is it so?")
    offers_api.scan_now("default")
    (o,) = offers_of(client)
    assert o["kind"] == "question" and "text" not in o["payload"]


# --- slant levelling ---


def _line(slope_deg, n=20, length=200.0):
    import math

    dx, dy = math.cos(math.radians(slope_deg)), -math.sin(math.radians(slope_deg))
    pts = [[i * length / n * dx, i * length / n * dy] for i in range(n)]
    return [{"id": "s", "type": "freedraw", "x": 100, "y": 300, "points": pts}]


def test_angle_of_slanted_line():
    assert latest_ink.writing_angle(_line(30)) == pytest.approx(30, abs=1)
    assert latest_ink.writing_angle(_line(-25)) == pytest.approx(-25, abs=1)


def test_angle_zero_for_horizontal_steep_and_blob():
    assert latest_ink.writing_angle(_line(0)) == 0.0
    assert latest_ink.writing_angle(_line(5)) == 0.0
    assert latest_ink.writing_angle(_line(75)) == 0.0
    blob = [{"x": 0, "y": 0, "points": [[x, y] for x in range(0, 50, 5) for y in range(0, 50, 5)]}]
    assert latest_ink.writing_angle(blob) == 0.0


def test_level_rotates_with_white_fill_and_zero_is_identity():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), (0, 0, 0)).save(buf, "PNG")
    png = buf.getvalue()
    assert latest_ink._level(png, 0.0) is png
    out = Image.open(io.BytesIO(latest_ink._level(png, 30.0)))
    assert out.size[0] > 200 and out.getpixel((0, 0)) == (255, 255, 255)


def test_poll_sends_levelled_crop(client, monkeypatch):
    seen = []
    monkeypatch.setattr(latest_ink, "_level", lambda png, a: seen.append(a) or png)
    setup(client, monkeypatch, Reader())
    poll()
    assert seen == [0.0]  # a horizontal row is left alone
