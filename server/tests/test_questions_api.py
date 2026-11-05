"""Questions API (INK-047): lifecycle, threads, validation, WebSocket push. Pull path only."""

import time

from fastapi.testclient import TestClient

from inkbridge import db
from inkbridge.api import app
from inkbridge.db import questions as q_db
from tests.test_ops_api import seed
from tests.test_ws import WS, recv

Q = "/documents/default/questions"


def chunk_id(client, element_id="user-a"):
    for c in client.get("/documents/default/regions?chunks=true").json():
        if c["status"] == "active" and element_id in c["element_ids"]:
            return c["id"]
    raise AssertionError("no chunk")


def ask(client, text="why?", **extra):
    r = client.post(Q, json={"text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def answer(client, qid, md="x", sources=()):
    return client.post(f"/questions/{qid}/answer", json={"answer_md": md, "sources": list(sources)})


def test_new_question_has_runner_fields(client):
    q = ask(client)
    assert q["runner_status"] == "pending" and q["runner_error"] is None
    assert client.get(f"/questions/{q['id']}").json()["runner_status"] == "pending"
    assert client.get(Q).json()["questions"][0]["runner_error"] is None


def test_set_runner_leaves_an_answered_question_alone(client):
    qid = ask(client)["id"]
    assert answer(client, qid).status_code == 200
    conn = db.connect()
    try:
        q = q_db.set_runner(conn, qid, "failed", "exit 2")
    finally:
        conn.close()
    assert q["status"] == "answered" and q["runner_status"] == "pending"
    assert q["runner_error"] is None


def test_lifecycle_answer(client):
    seed(client)
    cid = chunk_id(client)
    q = ask(client, focus_element_ids=["user-a"])
    assert q["status"] == "pending" and q["parent_id"] is None and q["history"] == []
    assert q["focus_chunk_ids"] == [cid]
    assert client.get(f"/questions/{q['id']}").json() == q
    assert [x["id"] for x in client.get(Q + "?status=pending").json()["questions"]] == [q["id"]]
    sources = [{"type": "chunk", "id": cid}, {"type": "note", "path": "a/b.md"}]
    r = answer(client, q["id"], "x", sources)
    assert r.status_code == 200
    got = r.json()
    assert got["status"] == "answered" and got["answer_md"] == "x" and got["sources"] == sources
    assert client.get(Q + "?status=pending").json()["questions"] == []
    assert len(client.get(Q + "?status=answered").json()["questions"]) == 1
    assert answer(client, q["id"]).status_code == 409


def test_lifecycle_cancel(client):
    q = ask(client)
    r = client.post(f"/questions/{q['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert answer(client, q["id"]).status_code == 409
    assert client.post(f"/questions/{q['id']}/cancel").status_code == 409
    q2 = ask(client)
    answer(client, q2["id"])
    assert client.post(f"/questions/{q2['id']}/cancel").status_code == 409


def test_follow_up_history_survives_restart(client):
    q1 = ask(client, "first")
    answer(client, q1["id"], "a1")
    q2 = ask(client, "second", parent_id=q1["id"])
    answer(client, q2["id"], "a2")
    q3 = ask(client, "third", parent_id=q2["id"])
    assert q3["parent_id"] == q2["id"]
    with TestClient(app) as c2:  # fresh process analogue: only the DB file carries over
        hist = c2.get(f"/questions/{q3['id']}").json()["history"]
    assert [h["id"] for h in hist] == [q1["id"], q2["id"]]
    assert [(h["text"], h["answer_md"], h["status"]) for h in hist] == [
        ("first", "a1", "answered"),
        ("second", "a2", "answered"),
    ]


def test_history_keeps_last_five_ancestors(client):
    parent, ids = None, []
    for i in range(7):
        q = ask(client, f"q{i}", **({"parent_id": parent} if parent else {}))
        ids.append(q["id"])
        parent = q["id"]
    hist = client.get(f"/questions/{ids[6]}").json()["history"]
    assert [h["id"] for h in hist] == ids[1:6]


def test_pull_path_with_no_runner(client, monkeypatch):
    monkeypatch.delenv("INKBRIDGE_RUNNER", raising=False)
    q = ask(client)
    time.sleep(0.2)  # nothing but answer/cancel may move a row off pending
    assert client.get(f"/questions/{q['id']}").json()["status"] == "pending"


def test_validation(client):
    assert client.post("/documents/nope/questions", json={"text": "x"}).status_code == 404
    assert client.post(Q, json={"text": ""}).status_code == 422
    r = client.post(Q, json={"text": "x", "parent_id": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "parent_not_found"
    other = client.post("/documents", json={"title": "other"}).json()["id"]
    oq = client.post(f"/documents/{other}/questions", json={"text": "o"}).json()
    r = client.post(Q, json={"text": "x", "parent_id": oq["id"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "parent_not_found"
    q = ask(client)
    for bad in (
        [{"type": "note", "id": "x"}],
        [{"type": "chunk", "path": "p"}],
        [{"type": "chunk", "id": "c", "extra": 1}],
    ):
        assert answer(client, q["id"], "x", bad).status_code == 422
    assert answer(client, q["id"], "").status_code == 422
    assert client.get(Q + "?status=bogus").status_code == 422
    assert client.get("/questions/nope").status_code == 404
    assert answer(client, "nope").status_code == 404
    assert client.post("/questions/nope/cancel").status_code == 404
    assert client.get(f"/questions/{q['id']}").json()["status"] == "pending"


def test_ws_pushes_question_updates(client):
    with client.websocket_connect(WS) as ws:
        q = ask(client)
        msg = recv(ws)
        assert msg["type"] == "question.update"
        assert msg["question"]["id"] == q["id"] and msg["question"]["status"] == "pending"
        answer(client, q["id"], "the answer")
        msg = recv(ws)
        assert msg["question"]["status"] == "answered"
        assert msg["question"]["answer_md"] == "the answer"
        q2 = ask(client)
        recv(ws)
        client.post(f"/questions/{q2['id']}/cancel")
        assert recv(ws)["question"]["status"] == "cancelled"


def test_focus_follows_chunk_ids_at_read_time(client):
    seed(client)
    q = ask(client, focus_element_ids=["user-a", "ghost"])
    assert q["focus_element_ids"] == ["user-a", "ghost"]  # unknown ids are accepted
    first = chunk_id(client)
    assert client.get(f"/questions/{q['id']}").json()["focus_chunk_ids"] == [first]
    merged = client.post(
        "/documents/default/chunks/merge", json={"chunk_ids": [first, chunk_id(client, "user-b")]}
    )
    assert merged.status_code == 200, merged.text
    got = client.get(f"/questions/{q['id']}").json()["focus_chunk_ids"]
    assert got == [chunk_id(client)] and got != [first]
