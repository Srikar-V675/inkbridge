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
