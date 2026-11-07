"""INK-136: the retrieve MCP tool."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_retrieve import canvas_with_reading


@pytest.fixture
def api(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def two_canvases(client):
    a = canvas_with_reading(client, "Optimisation", "gradient descent notes", prefix="a")
    b = canvas_with_reading(client, "Calculus", "gradient of the loss", prefix="b")
    return a[0], b[0]


def test_retrieve_is_registered_with_scope_and_k():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    props = tools["retrieve"].input_schema["properties"]
    assert {"query", "scope", "k", "document_id"} <= set(props)
    assert props["scope"]["enum"] == ["canvas", "all"]
    assert (props["k"]["minimum"], props["k"]["maximum"]) == (1, 50)


def test_tool_finds_across_canvases(api):
    a, b = two_canvases(api)
    assert {h["canvas"] for h in call("retrieve", query="gradient", scope="all")["results"]} == {a, b}
    only = call("retrieve", query="gradient", scope="canvas", document_id=a)["results"]
    assert [h["canvas"] for h in only] == [a]


def test_default_scope_is_the_configured_document(api, monkeypatch):
    _, other = two_canvases(api)
    monkeypatch.setenv("INKBRIDGE_DOCUMENT", other)
    server.set_client(ApiClient(api))
    hits = call("retrieve", query="gradient")["results"]
    assert [h["canvas"] for h in hits] == [other]


def test_unknown_canvas_is_a_tool_error(api):
    with pytest.raises(ToolError, match="Check document_id"):
        call("retrieve", query="gradient", document_id="nope")
