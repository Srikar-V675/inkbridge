"""Streaming answers (INK-176): partial appends, deltas over the WebSocket, final replaces."""

from inkbridge import db
from inkbridge.db import questions as q_db
from tests.test_questions_api import answer, ask
from tests.test_ws import WS, recv


def part(client, qid, text):
    return client.post(f"/questions/{qid}/answer", json={"answer_md": text, "final": False})


def test_partial_appends_and_pushes_delta(client):
    qid = ask(client)["id"]
    with client.websocket_connect(WS) as ws:
        for t in ("he", "llo"):
            assert part(client, qid, t).status_code == 200
        assert recv(ws) == {"type": "question.delta", "id": qid, "seq": 1, "text": "he"}
        assert recv(ws) == {"type": "question.delta", "id": qid, "seq": 2, "text": "llo"}
    q = client.get(f"/questions/{qid}").json()
    assert (q["partial_answer"], q["partial_seq"], q["status"]) == ("hello", 2, "pending")


def test_final_replaces_partial(client):
    qid = ask(client)["id"]
    part(client, qid, "he")
    with client.websocket_connect(WS) as ws:
        assert answer(client, qid, "hello world").status_code == 200
        msg = recv(ws)
    assert msg["type"] == "question.update" and msg["question"]["partial_answer"] is None
    q = client.get(f"/questions/{qid}").json()
    assert q["status"] == "answered" and q["answer_md"] == "hello world"
    assert q["partial_answer"] is None


def test_partial_on_answered_is_409(client):
    qid = ask(client)["id"]
    answer(client, qid)
    assert part(client, qid, "x").status_code == 409


def test_partial_too_long_is_422(client):
    qid = ask(client)["id"]
    assert part(client, qid, "a" * 12_000).status_code == 200
    r = part(client, qid, "a" * 12_000)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "partial_too_long"


def test_reset_partial_clears(client):
    qid = ask(client)["id"]
    part(client, qid, "abc")
    conn = db.connect()
    try:
        q_db.reset_partial(conn, qid)
        q = q_db.get_question(conn, qid)
    finally:
        conn.close()
    assert (q["partial_answer"], q["partial_seq"]) == (None, 0)
