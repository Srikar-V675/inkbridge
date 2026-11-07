"""INK-136: retrieval across canvases (keyword first), decision 0079."""

import shutil

import pytest

from inkbridge import db
from tests.fts_check import fts_problems
from tests.test_chunk_persistence import row
from tests.test_questions_api import answer, ask


def test_migration_0010_backfills_answered_questions(tmp_path, monkeypatch):
    old = tmp_path / "old"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("000[1-7]_*.sql")):
        shutil.copy(f, old / f.name)
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v7.db")
    db.migrate(conn)
    db.ensure_default_document(conn)
    conn.execute(
        "INSERT INTO questions (id, document_id, text, answer_md, status, created_at)"
        " VALUES ('q1','default','why?','because zebras','answered','t')"
    )
    conn.execute(
        "INSERT INTO questions (id, document_id, text, status, created_at)"
        " VALUES ('q2','default','pending?','pending','t')"
    )
    conn.commit()
    monkeypatch.undo()
    assert 10 in db.migrate(conn)
    rows = conn.execute("SELECT question_id, question, answer FROM answer_fts").fetchall()
    assert [tuple(r) for r in rows] == [("q1", "why?", "because zebras")]
    conn.close()


def test_answering_indexes_and_cancel_does_not(client):
    done, cancelled = ask(client)["id"], ask(client, "never answered")["id"]
    assert answer(client, done, "photosynthesis notes").status_code == 200
    assert client.post(f"/questions/{cancelled}/cancel").status_code == 200
    conn = db.connect()
    try:
        ids = [r["question_id"] for r in conn.execute("SELECT question_id FROM answer_fts")]
    finally:
        conn.close()
    assert ids == [done]


def test_answer_fts_detector_bites(client):
    qid = ask(client)["id"]
    assert answer(client, qid, "some answer").status_code == 200
    conn = db.connect()
    try:
        assert fts_problems(conn) == []
        conn.execute("DELETE FROM answer_fts WHERE question_id = ?", (qid,))
        assert any(qid in p for p in fts_problems(conn))
        conn.execute(
            "INSERT INTO answer_fts (question_id, document_id, question, answer)"
            " VALUES (?, 'default', 'why?', 'some answer')",
            (qid,),
        )
        assert fts_problems(conn) == []
    finally:
        conn.close()
