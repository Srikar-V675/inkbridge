"""INK-072 item 7: successor_of has no foreign key (decision 0027); this guards it in tests."""

import pytest

from inkbridge import db
from tests.integrity_check import successor_problems
from tests.test_chunk_persistence import Canvas, row


def problems():
    conn = db.connect()
    try:
        return successor_problems(conn)
    finally:
        conn.close()


def test_split_merge_and_undo_leave_no_dangling_successor(client):
    canvas = Canvas(client, row("a", 6))
    for i in range(3, 6):  # split
        canvas.el(f"a{i}")["y"] += 400
    canvas.put()
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM regions WHERE successor_of IS NOT NULL").fetchone()[0]
    conn.close()
    assert problems() == []
    for i in range(3, 6):  # merge back
        canvas.el(f"a{i}")["y"] -= 400
    canvas.put()
    assert problems() == []
    canvas.elements[:] = [e for e in canvas.elements if e["id"] not in ("a0", "a1")]
    canvas.put()  # shrink
    assert problems() == []


@pytest.mark.fts_unchecked
def test_a_dangling_successor_is_reported(client):
    Canvas(client, row("a", 3))
    conn = db.connect()
    try:
        conn.execute("UPDATE regions SET successor_of = 'ghost'")
        conn.commit()
        (msg,) = successor_problems(conn)
    finally:
        conn.close()
    assert "missing region" in msg


@pytest.mark.fts_unchecked
def test_cross_document_and_loop_are_reported(client):
    Canvas(client, row("a", 3))
    other = client.post("/documents", json={"title": "x"}).json()["id"]
    conn = db.connect()
    try:
        (rid,) = [r[0] for r in conn.execute("SELECT id FROM regions")]
        cols = [c[1] for c in conn.execute("PRAGMA table_info(regions)")]
        sel = ", ".join(
            {"id": "'x2'", "document_id": "?", "successor_of": "?"}.get(c, c) for c in cols
        )
        conn.execute(
            f"INSERT INTO regions ({', '.join(cols)}) SELECT {sel} FROM regions WHERE id = ?",
            (other, rid, rid),
        )
        conn.commit()
        assert any("another document" in p for p in successor_problems(conn))
        conn.execute("UPDATE regions SET successor_of = ? WHERE id = ?", (rid, rid))
        conn.commit()
        assert any("loops" in p for p in successor_problems(conn))
    finally:
        conn.close()
