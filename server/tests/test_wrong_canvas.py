"""INK-191: a wrong-canvas call names both canvases (decision 0108)."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_agent_tasks import claim, new_task, op
from tests.test_ops_api import seed
from tests.test_questions_api import ask, chunk_id


def canvas_b(client):
    return client.post("/documents", json={"title": "b"}).json()["id"]


def test_chunk_not_found_names_both_canvases(client):
    seed(client)
    cid = chunk_id(client)
    b = canvas_b(client)
    payload = {"source": "flowchart TD\nA-->B", "source_kind": "mermaid", "from_chunks": [cid]}
    r = client.post(f"/documents/{b}/ops", json={"type": "draw_diagram", "payload": payload})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "chunk_not_found"
    assert d["document_id"] == b and d["found_on"] == "default" and b in d["msg"]
    payload["from_chunks"] = ["nope"]
    d = client.post(f"/documents/{b}/ops", json={"type": "draw_diagram", "payload": payload}).json()[
        "detail"
    ]
    assert d["found_on"] is None and b in d["msg"]


def test_question_in_other_canvas_names_both(client):
    q = ask(client)
    b = canvas_b(client)
    for final in (True, False):
        r = client.post(
            f"/questions/{q['id']}/answer", json={"answer_md": "x", "document_id": b, "final": final}
        )
        d = r.json()["detail"]
        assert r.status_code == 409 and d["code"] == "question_other_canvas"
        assert "default" in d["msg"] and b in d["msg"]
    r = client.post("/questions/nope/answer", json={"answer_md": "x", "document_id": b})
    assert r.status_code == 404 and "nope" in r.json()["detail"] and b in r.json()["detail"]
    assert client.post(f"/questions/{q['id']}/answer", json={"answer_md": "x"}).status_code == 200


def test_question_not_found_is_not_bare(client):
    r = client.get("/questions/nope")
    assert r.status_code == 404 and "nope" in r.json()["detail"]


def test_op_with_other_canvas_question_id_names_canvas(client):
    q = ask(client)
    b = canvas_b(client)
    r = client.post(
        f"/documents/{b}/ops",
        json={"type": "write_text", "payload": {"text": "hi", "question_id": q["id"]}},
    )
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "question_not_found"
    assert d["document_id"] == b and b in d["msg"]


def test_task_other_canvas_names_both(client):
    tid = new_task("question")
    claim(client, tid)
    b = canvas_b(client)
    r = op(client, tid, doc=b)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "task_other_canvas"
    assert "default" in d["msg"] and b in d["msg"] and tid in d["msg"]


# --- MCP tools -------------------------------------------------------------------------------


@pytest.fixture
def mcp_client(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def test_answer_question_wrong_canvas_is_tool_error_naming_canvas(mcp_client):
    q = ask(mcp_client)
    b = canvas_b(mcp_client)
    with pytest.raises(ToolError) as e:
        call("answer_question", question_id=q["id"], answer_md="x", document_id=b)
    assert "default" in str(e.value) and b in str(e.value)
    out = call("answer_question", question_id=q["id"], answer_md="x")
    assert out["document_id"] == "default"


def test_results_echo_document_id(mcp_client):
    b = canvas_b(mcp_client)
    out = call("list_questions", document_id=b)
    assert out["document_id"] == b and out["questions"] == []
    assert call("write_text", text="hi", document_id=b)["document_id"] == b
    assert call("write_text", text="hi")["document_id"] == "default"


def test_write_text_other_canvas_chunk_error_names_canvas(mcp_client):
    seed(mcp_client)
    cid = chunk_id(mcp_client)
    b = canvas_b(mcp_client)
    with pytest.raises(ToolError, match=b):
        call("write_text", text="hi", anchor=cid, document_id=b)
