"""INK-133: agent tasks (decision 0095): table, lifecycle hooks, API, op limits."""

import sqlite3

import pytest

from inkbridge import db
from inkbridge.db import tasks as tasks_db
from tests.test_offers_api import chunk, clock, post  # noqa: F401 - fixtures
from tests.test_questions_api import answer, ask


def tasks_of(client, **q):
    r = client.get("/documents/default/tasks", params=q)
    assert r.status_code == 200, r.text
    return r.json()["tasks"]


def test_question_creates_task_and_answer_finishes_it(client):
    a, b = ask(client, "one"), ask(client, "two")
    ts = tasks_of(client)
    assert [t["question_id"] for t in ts] == [a["id"], b["id"]]
    assert {t["status"] for t in ts} == {"pending"} and ts[0]["mode"] == "question"
    assert answer(client, a["id"]).status_code == 200
    assert client.post(f"/questions/{b['id']}/cancel").status_code == 200
    got = {t["question_id"]: t["status"] for t in tasks_of(client)}
    assert got == {a["id"]: "done", b["id"]: "cancelled"}


def test_tap_offer_creates_task(client, chunk):  # noqa: F811
    o = post(client, chunk, kind="sketch")
    assert client.post(f"/offers/{o['id']}/tap").status_code == 200
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM agent_tasks").fetchall()
        assert len(rows) == 1 and rows[0]["kind"] == "offer" and rows[0]["offer_id"] == o["id"]
        assert conn.execute("SELECT task_id FROM offers").fetchone()[0] == rows[0]["id"]
        assert tasks_db.get_task(conn, rows[0]["id"])["mode"] == "diagram"
    finally:
        conn.close()


def test_claim_is_exclusive(client):
    q = ask(client)
    conn = db.connect()
    try:
        tid = tasks_db.task_for_question(conn, q["id"])["id"]
        assert tasks_db.claim(conn, tid, "mcp")["status"] == "running"
        with pytest.raises(tasks_db.InvalidTransition):
            tasks_db.claim(conn, tid, "runner")
    finally:
        conn.close()


def test_migration_backfills_pending_questions(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db")
    conn.row_factory = sqlite3.Row
    from inkbridge.db import migrations as m

    files = sorted(m.MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        if f.name.startswith("0016"):
            break
        conn.executescript(f.read_text())
    conn.execute("INSERT INTO documents (id, title, updated_at) VALUES ('d','t','x')")
    for qid, st in (("p", "pending"), ("a", "answered")):
        conn.execute(
            "INSERT INTO questions (id, document_id, text, focus_element_ids, status, created_at)"
            " VALUES (?, 'd', 'q', '[]', ?, 'x')",
            (qid, st),
        )
    conn.executescript((m.MIGRATIONS_DIR / "0016_agent_tasks.sql").read_text())
    got = conn.execute("SELECT question_id, status FROM agent_tasks").fetchall()
    assert [tuple(r) for r in got] == [("p", "pending")]


def test_runner_count_today_ignores_questions_and_old_claims(client):
    ask(client)
    conn = db.connect()
    try:
        doc = "default"
        ids = []
        for kind, by, at in (
            ("offer", "runner", None),
            ("offer", "mcp", None),
            ("offer", "runner", "2000-01-01T00:00:00+00:00"),
            ("question", "runner", None),
        ):
            t = tasks_db.create_task(conn, doc, kind, input={"mode": "link"})
            ids.append((t["id"], by, at))
        for tid, by, at in ids:
            conn.execute(
                "UPDATE agent_tasks SET claimed_by=?, claimed_at=COALESCE(?, ?) WHERE id=?",
                (by, at, db._now(), tid),
            )
        conn.commit()
        assert tasks_db.runner_count_today(conn) == 1
    finally:
        conn.close()
