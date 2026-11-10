"""MCP list_questions and answer_question (INK-047): the pull path, no runner involved."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_ops_api import seed
from tests.test_questions_api import Q, ask, chunk_id
from tests.test_ws import WS, recv


@pytest.fixture
def mcp_client(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def test_list_questions_pull_path_no_runner(mcp_client, monkeypatch):
    monkeypatch.delenv("INKBRIDGE_RUNNER", raising=False)
    a, b = ask(mcp_client, "one"), ask(mcp_client, "two")
    out = call("list_questions")["questions"]
    assert [q["id"] for q in out] == [a["id"], b["id"]]
    assert {"id", "text", "focus_chunk_ids", "parent_id", "history", "status", "created_at"} <= set(
        out[0]
    )
    assert len(call("list_questions", limit=1)["questions"]) == 1
    assert call("list_questions", status="answered")["questions"] == []
    other = mcp_client.post("/documents", json={"title": "o"}).json()["id"]
    assert call("list_questions", document_id=other)["questions"] == []


def test_list_questions_includes_history(mcp_client):
    q1 = ask(mcp_client, "first")
    call("answer_question", question_id=q1["id"], answer_md="a1")
    q2 = ask(mcp_client, "second", parent_id=q1["id"])
    got = call("list_questions")["questions"]
    assert [q["id"] for q in got] == [q2["id"]]
    assert got[0]["parent_id"] == q1["id"]
    assert [(h["text"], h["answer_md"]) for h in got[0]["history"]] == [("first", "a1")]


def test_answer_question_persists_and_pushes(mcp_client):
    seed(mcp_client)
    cid = chunk_id(mcp_client)
    q = ask(mcp_client, focus_element_ids=["user-a"])
    with mcp_client.websocket_connect(WS) as ws:
        out = call(
            "answer_question",
            question_id=q["id"],
            answer_md="42",
            sources=[{"type": "chunk", "id": cid}],
        )
        assert out["status"] == "answered"
        msg = recv(ws)
    assert msg["type"] == "question.update" and msg["question"]["answer_md"] == "42"
    got = mcp_client.get(f"/questions/{q['id']}").json()
    assert got["status"] == "answered" and got["sources"] == [{"type": "chunk", "id": cid}]
    assert mcp_client.get(Q + "?status=pending").json()["questions"] == []


def test_answer_errors_are_tool_errors(mcp_client):
    done, gone = ask(mcp_client), ask(mcp_client)
    call("answer_question", question_id=done["id"], answer_md="a")
    mcp_client.post(f"/questions/{gone['id']}/cancel")
    for qid in ("nope", done["id"], gone["id"]):
        with pytest.raises(ToolError, match="list_questions"):
            call("answer_question", question_id=qid, answer_md="again")
    live = ask(mcp_client)
    with pytest.raises(ToolError):
        call("answer_question", question_id=live["id"], answer_md="x", sources=[{"type": "note"}])
    assert mcp_client.get(f"/questions/{live['id']}").json()["status"] == "pending"


def test_answer_question_canvas_text(mcp_client):
    q = ask(mcp_client, "why")
    call("answer_question", question_id=q["id"], answer_md="a", canvas_text="c")
    got = call("list_questions", status="answered")["questions"]
    assert got[0]["canvas_text"] == "c"


def test_answer_question_final_false_appends(mcp_client):
    q = ask(mcp_client)
    with mcp_client.websocket_connect(WS) as ws:
        out = call("answer_question", question_id=q["id"], answer_md="ab", final=False)
        assert out == {"id": q["id"], "status": "pending", "document_id": "default", "seq": 1}
        assert recv(ws)["type"] == "question.delta"
    assert call("list_questions")["questions"][0]["partial_answer"] == "ab"
    out = call("answer_question", question_id=q["id"], answer_md="abc")
    assert out == {"id": q["id"], "status": "answered", "document_id": "default"}
    assert mcp_client.get(f"/questions/{q['id']}").json()["partial_answer"] is None


def test_answer_question_final_false_on_answered_points_at_list(mcp_client):
    q = ask(mcp_client)
    call("answer_question", question_id=q["id"], answer_md="x")
    with pytest.raises(ToolError, match="list_questions"):
        call("answer_question", question_id=q["id"], answer_md="y", final=False)
