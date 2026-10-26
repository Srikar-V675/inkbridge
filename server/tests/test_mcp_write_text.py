"""MCP write_text and create_canvas (INK-043)."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from inkbridge.placement import estimate_size, overlaps
from inkbridge.regions import bbox_of
from tests.test_ops_api import USER_A, USER_B, seed


@pytest.fixture
def mcp_client(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def box_of(out, text):
    w, h = estimate_size("write_text", {"text": text})
    return {**out["placement"], "width": w, "height": h}


def test_write_text_queues_a_draft_op(mcp_client):
    out = call("write_text", text="Learning rate")
    assert out["status"] == "pending" and out["placement"] == {"x": 0, "y": 0}
    op = mcp_client.get(f"/ops/{out['op_id']}").json()
    assert op["type"] == "write_text" and op["payload"]["text"] == "Learning rate"


def test_stacked_writes_never_overlap_ink_or_each_other(mcp_client):
    seed(mcp_client)
    chunk = mcp_client.get("/documents/default/regions", params={"chunks": True}).json()[0]["id"]
    ink = [bbox_of([e]) for e in (USER_A, USER_B)]
    placed = []
    for i in range(8):
        text = f"note {i}\nwith a second, longer line"
        args = {"text": text, **({"anchor": chunk} if i % 3 == 0 else {})}
        placed.append(box_of(call("write_text", **args), text))
    for i, box in enumerate(placed):
        assert not any(overlaps(box, o) for o in ink), box
        assert not any(overlaps(box, o) for o in placed[:i]), box


def test_create_canvas_then_write_into_it_from_the_origin_down(mcp_client):
    out = call("create_canvas", title="Backpropagation")
    doc = out["document_id"]
    assert out["url"].endswith(f"/?canvas={doc}")
    assert mcp_client.get(f"/documents/{doc}/scene").json() == {"version": 0, "elements": []}
    first = call("write_text", text="Chain rule", document_id=doc)
    second = call("write_text", text="Gradients flow backwards", document_id=doc)
    assert first["placement"] == {"x": 0, "y": 0}
    assert second["placement"]["x"] == 0 and second["placement"]["y"] > 0
    assert not overlaps(box_of(first, "Chain rule"), box_of(second, "Gradients flow backwards"))
    ops = mcp_client.get(f"/documents/{doc}/ops").json()["ops"]
    assert len(ops) == 2 and mcp_client.get("/documents/default/ops").json()["ops"] == []


def test_create_canvas_only_ever_adds(mcp_client):
    seed(mcp_client)
    before = mcp_client.get("/documents/default/scene").json()
    a = call("create_canvas", title="Same title")
    b = call("create_canvas", title="Same title")
    assert a["document_id"] != b["document_id"]
    assert mcp_client.get("/documents/default/scene").json() == before


def test_write_text_cannot_name_existing_ink(mcp_client):
    seed(mcp_client)
    with pytest.raises(ToolError, match="existing_element_id"):
        call("write_text", text="x", anchor="user-a")
    with pytest.raises(ToolError, match="existing_element_id"):
        call("write_text", text="user-b")
    assert mcp_client.get("/documents/default/ops").json()["ops"] == []


def test_write_text_errors_say_what_to_do(mcp_client):
    with pytest.raises(ToolError, match="Not found.*document_id"):
        call("write_text", text="x", document_id="nope")
    with pytest.raises(ToolError, match="anchor"):
        call("write_text", text="x", anchor="no-such-chunk")
    with pytest.raises(ToolError, match="title"):
        call("create_canvas", title="   ")


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"write_text", "create_canvas", "draw_diagram"} <= names
