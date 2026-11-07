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


# --- API: routes, op limit, WebSocket line ---------------------------------------------------


def claim(client, tid, by="mcp"):
    r = client.post(f"/tasks/{tid}/claim", json={"claimed_by": by})
    assert r.status_code == 200, r.text
    return r.json()


def new_task(mode, doc="default", kind="offer"):
    conn = db.connect()
    try:
        t = tasks_db.create_task(conn, doc, kind, input={"mode": mode})
        conn.commit()
        return t["id"]
    finally:
        conn.close()


def op(client, task_id=None, type_="write_text", doc="default"):
    payload = {"text": "hi"} if type_ == "write_text" else {"mermaid": "flowchart TD\nA-->B"}
    if task_id:
        payload["task_id"] = task_id
    return client.post(f"/documents/{doc}/ops", json={"type": type_, "payload": payload})


def test_op_past_task_limit_is_refused(client):
    tid = tasks_of(client_with_question(client))[0]["id"]
    claim(client, tid)
    for _ in range(3):
        assert op(client, tid).status_code == 201
    r = op(client, tid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_op_limit"


def client_with_question(client):
    ask(client)
    return client


def test_op_type_outside_mode_refused(client):
    d, link = new_task("diagram"), new_task("link")
    claim(client, d)
    claim(client, link)
    assert op(client, d).json()["detail"]["code"] == "task_mode"
    assert op(client, link, "draw_diagram").json()["detail"]["code"] == "task_mode"
    assert op(client, link).json()["detail"]["code"] == "task_mode"


def test_op_needs_a_running_task(client):
    pending = new_task("question")
    assert op(client, pending).json()["detail"]["code"] == "task_not_running"
    assert op(client, "nope").status_code == 404
    client.post("/documents", json={"title": "o"})
    other = client.post("/documents", json={"title": "x"}).json()["id"]
    t = new_task("question", doc=other)
    claim(client, t)
    assert op(client, t).json()["detail"]["code"] == "task_other_canvas"


def test_op_without_task_id_unchanged(client):
    r = op(client)
    assert r.status_code == 201


def test_op_retry_does_not_count_twice(client):
    t = new_task("diagram")
    claim(client, t)
    body = {
        "type": "draw_diagram",
        "op_id": "same1",
        "payload": {"mermaid": "flowchart TD\nA-->B", "task_id": t},
    }
    assert client.post("/documents/default/ops", json=body).status_code == 201
    assert client.post("/documents/default/ops", json=body).status_code in (200, 409)
    conn = db.connect()
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM agent_ops WHERE task_id=?", (t,)).fetchone()[0] == 1
        )
    finally:
        conn.close()


def test_claim_complete_routes_and_ws_line(client):
    t = new_task("link")
    with client.websocket_connect("/ws?document=default") as ws:
        got = claim(client, t)
        assert got["status"] == "running"
        msg = ws.receive_json()
        assert (
            msg["type"] == "task.status" and msg["task_id"] == t and msg["line"] == "Working on it"
        )
        assert client.post(f"/tasks/{t}/claim", json={"claimed_by": "x"}).status_code == 409
        r = client.post(f"/tasks/{t}/complete", json={"status": "failed", "error": "boom"})
        assert r.status_code == 200
        assert ws.receive_json()["line"] == "Failed: boom"
    assert client.post("/tasks/nope/claim", json={"claimed_by": "x"}).status_code == 404


def test_complete_question_task_needs_answer(client):
    q = ask(client)
    tid = tasks_of(client)[0]["id"]
    claim(client, tid)
    r = client.post(f"/tasks/{tid}/complete", json={"status": "done"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "question_unanswered"
    assert tasks_of(client, status="running")[0]["question"]["id"] == q["id"]


@pytest.mark.parametrize(
    ("raw", "want"), [(None, 30), ("", 30), ("0", 0), ("5", 5), ("-1", 30), ("x", 30)]
)
def test_agent_daily_tasks_env(monkeypatch, raw, want):
    from inkbridge import config

    monkeypatch.delenv("INKBRIDGE_AGENT_DAILY_TASKS", raising=False)
    if raw is not None:
        monkeypatch.setenv("INKBRIDGE_AGENT_DAILY_TASKS", raw)
    assert config.agent_daily_tasks() == want
