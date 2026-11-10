"""INK-060: get_subgraph and canvas_components over MCP."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.agent import mermaid
from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_chunk_persistence import Canvas, row
from tests.test_graph_api import chain


@pytest.fixture
def api(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def test_both_tools_are_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"get_subgraph", "canvas_components"} <= names


def test_get_subgraph_returns_chunks_to_depth(api):
    _, (a, b, c, _d) = chain(api)
    body = call("get_subgraph", chunk_id=b)
    assert {n["id"]: n["distance"] for n in body["nodes"]} == {b: 0, a: 1, c: 1}
    assert body["omitted_nodes"] == 0 and "mermaid" not in body
    assert len(call("get_subgraph", chunk_id=b, depth=2)["nodes"]) == 4


def test_to_chunk_id_returns_the_path(api):
    _, (a, b, c, d) = chain(api)
    body = call("get_subgraph", chunk_id=a, to_chunk_id=d)
    assert (
        body["found"] and body["length"] == 3 and [n["id"] for n in body["nodes"]] == [a, b, c, d]
    )


def test_mermaid_flag(api):
    _, (a, *_) = chain(api)
    assert mermaid.is_flowchart(call("get_subgraph", chunk_id=a, mermaid=True)["mermaid"])


def test_dead_end_chunk_raises_with_read_canvas_advice(api):
    canvas = Canvas(api, row("a", 3) + row("b", 3, y=500))
    gone = canvas.chunk_of("a0")["id"]
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    with pytest.raises(ToolError, match="read_canvas"):
        call("get_subgraph", chunk_id=gone)


def test_unknown_chunk_raises(api):
    chain(api)
    with pytest.raises(ToolError, match="not on this canvas"):
        call("get_subgraph", chunk_id="nope")


def test_canvas_components_lists_groups(api):
    chain(api)
    body = call("canvas_components")
    assert body["chunk_count"] == 4 and [c["size"] for c in body["components"]] == [4]


def test_max_nodes_is_passed_through(api):
    _, (_a, b, *_) = chain(api)
    body = call("get_subgraph", chunk_id=b, depth=3, max_nodes=2)
    assert len(body["nodes"]) == 2 and body["omitted_nodes"] == 2


def test_path_errors_are_tool_errors(api):
    old, (a, *_) = chain(api)
    with pytest.raises(ToolError, match="not on this canvas"):
        call("get_subgraph", chunk_id=a, to_chunk_id="nope")
    for e in (
        old.elements
    ):  # a full save no longer replaces the scene: delete the chain, then start over
        e["isDeleted"] = True
    old.put()
    canvas = Canvas(api, row("p", 3) + row("q", 3, y=500))
    gone = canvas.chunk_of("p0")["id"]
    other = canvas.chunk_of("q0")["id"]
    for i in range(3):
        canvas.el(f"p{i}")["isDeleted"] = True
    canvas.put()
    with pytest.raises(ToolError, match="read_canvas"):
        call("get_subgraph", chunk_id=other, to_chunk_id=gone)


def test_non_dict_error_bodies_do_not_crash():
    import httpx

    from inkbridge.mcp.client import _coded_detail, _detail_text

    for body in ([1, 2], "x", {"detail": "Not Found"}):
        r = httpx.Response(404, json=body)
        assert _coded_detail(r) == ""
        _detail_text(r)
    assert _coded_detail(httpx.Response(404, json={"detail": {"code": "c", "msg": "m"}})) == "m"
