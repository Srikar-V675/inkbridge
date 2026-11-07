"""INK-133: the pull path through MCP tools, as a second client would use it."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_agent_tasks import new_task
from tests.test_questions_api import ask


@pytest.fixture
def mcp_client(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def test_second_client_works_a_question_task(mcp_client):
    q = ask(mcp_client, "why?")
    (t,) = call("list_tasks")["tasks"]
    assert t["question_id"] == q["id"] and t["question"]["text"] == "why?"
    got = call("claim_task", task_id=t["id"])
    assert got["status"] == "running" and got["op_limit"] == 3
    assert "write_text" in got["allowed_op_types"]
    with pytest.raises(ToolError, match="already claimed"):
        call("claim_task", task_id=t["id"])
    for _ in range(3):
        call("write_text", text="x", task_id=t["id"])
    with pytest.raises(ToolError, match="already made 3 of 3"):
        call("write_text", text="x", task_id=t["id"])
    with pytest.raises(ToolError, match="answer the question first"):
        call("complete_task", task_id=t["id"])
    call("answer_question", question_id=q["id"], answer_md="because")
    assert call("list_tasks", status="done")["tasks"][0]["id"] == t["id"]


def test_complete_task_on_an_offer_task(mcp_client):
    tid = new_task("diagram")
    call("claim_task", task_id=tid)
    with pytest.raises(ToolError, match="not allowed in this task"):
        call("write_text", text="x", task_id=tid)
    assert call("complete_task", task_id=tid)["status"] == "done"
