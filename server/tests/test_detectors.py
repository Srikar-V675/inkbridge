"""INK-132: detectors turn the canvas into offer candidates with no model."""

import pytest

from inkbridge import db
from inkbridge.agent import detectors
from tests.test_chunk_persistence import Canvas, row
from tests.test_search import recognise


def scan():
    conn = db.connect()
    try:
        return detectors.scan(conn, "default")
    finally:
        conn.close()


def of_kind(kind):
    return [c for c in scan() if c.kind == kind]


def chunks(client, *texts):
    """One chunk per text, rows 500 px apart, each read as the given text (None = no reading)."""
    canvas = Canvas(client, [e for i, _ in enumerate(texts) for e in row(f"r{i}", 3, y=500 * i)])
    out = []
    for i, t in enumerate(texts):
        c = canvas.chunk_of(f"r{i}0")
        if t is not None:
            recognise(c, t)
        out.append(canvas.chunk_of(f"r{i}0"))
    return canvas, out


def test_question(client):
    _, (a, b, c) = chunks(client, "Why does it rise?", "what is a tensor", "Meeting notes")
    found = {x.anchor: x for x in of_kind("question")}
    assert set(found) == {a["id"], b["id"]}
    assert found[a["id"]].payload == {"action": "answer", "prepare": True, "key": a["text_hash"]}
    assert not [x for x in of_kind("question") if x.anchor == c["id"]]


def test_question_mark_ends_text(client):
    _, (a,) = chunks(client, "Done?")
    assert [x.anchor for x in of_kind("question")] == [a["id"]]


def test_open_equation(client):
    _, (a, b) = chunks(client, "x + 2 =", "x = 2")
    (found,) = of_kind("open_equation")
    assert found.anchor == a["id"] and found.payload["action"] == "answer"
    assert found.payload["key"] == a["text_hash"]


def test_dangling_arrow(client):
    _, (a, b) = chunks(client, "x", "y")
    conn = db.connect()
    conn.execute("UPDATE regions SET kind='connector' WHERE id=?", (a["id"],))
    conn.commit()
    conn.close()
    (found,) = of_kind("dangling_arrow")
    assert found.anchor == a["id"] and found.payload["action"] == "ask_user"
    assert found.payload["key"] == a["content_hash"]


def test_stale_note(client):
    canvas, (a,) = chunks(client, "reading A")
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(a["id"], a["text_hash"])])
    conn.close()
    assert of_kind("stale_note") == []
    recognise(a, "other words", source="user")
    new = canvas.chunk_of("r00")
    (found,) = of_kind("stale_note")
    assert found.anchor == a["id"]
    assert found.payload == {"action": "note", "note": "n1", "key": new["text_hash"]}
    assert new["text_hash"] != a["text_hash"]


def test_stale_note_ignores_unread_and_inactive(client):
    canvas, (a, b) = chunks(client, None, "read")
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(a["id"], "f" * 64), ("gone00000000", "f" * 64)])
    conn.close()
    assert of_kind("stale_note") == []


def test_to_note(client):
    _, cs = chunks(client, *["w"] * 7)
    assert of_kind("to_note") == []
    _, cs = chunks(client, *["w"] * 8)
    (found,) = of_kind("to_note")
    assert found.payload == {"action": "note", "key": "canvas"}
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(cs[0]["id"], "f" * 64)])
    conn.close()
    assert of_kind("to_note") == []
