"""INK-135: canvas brief and what_changed (decision 0093)."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge import db
from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_chunk_persistence import Canvas, row


@pytest.fixture
def conn(client):
    c = db.connect()
    yield c
    c.close()


def head(conn):
    return conn.execute("SELECT version FROM scenes WHERE document_id = 'default'").fetchone()[0]


def test_what_changed_lists_only_chunks_with_newer_elements(client, conn):
    canvas = Canvas(client, row("a", 4) + row("b", 3, y=500))
    a, b = canvas.chunk_of("a0")["id"], canvas.chunk_of("b0")["id"]
    seq1 = head(conn)
    canvas.el("b1")["x"] += 3
    canvas.put()
    got = db.what_changed(conn, "default", since=seq1)
    assert [(c["id"], c["change"]) for c in got["chunks"]] == [(b, "changed")]
    assert {c["id"] for c in db.what_changed(conn, "default", since=0)["chunks"]} == {a, b}


def test_deleted_chunk_is_removed(client, conn):
    canvas = Canvas(client, row("a", 4) + row("b", 3, y=500))
    b = canvas.chunk_of("b0")["id"]
    seq1 = head(conn)
    for e in canvas.elements:
        if e["id"].startswith("b"):
            e["isDeleted"] = True
    canvas.put()
    got = db.what_changed(conn, "default", since=seq1)["chunks"]
    assert [(c["id"], c["change"]) for c in got] == [(b, "removed")]


def test_last_seen_cursor(client, conn):
    canvas = Canvas(client, row("a", 4))
    first = db.what_changed(conn, "default")
    assert len(first["chunks"]) == 1 and first["since"] == 0
    db.what_changed(conn, "default", mark_seen=False)
    assert db.get_memory(conn, "default")["last_seen_seq"] == 0
    db.what_changed(conn, "default", mark_seen=True)
    assert db.get_memory(conn, "default")["last_seen_seq"] == head(conn)
    assert db.what_changed(conn, "default")["chunks"] == []
    canvas.elements += row("b", 3, y=500)
    canvas.put()
    got = db.what_changed(conn, "default")["chunks"]
    assert [c["id"] for c in got] == [canvas.chunk_of("b0")["id"]]


def test_set_brief_keeps_cursor(client, conn):
    Canvas(client, row("a", 4))
    db.set_brief(conn, "default", "one")
    db.what_changed(conn, "default", mark_seen=True)
    mem = db.set_brief(conn, "default", "two")
    assert mem["brief"] == "two" and mem["last_seen_seq"] == head(conn)
    assert db.get_memory(conn, "default") == mem


def test_unknown_document_raises(conn):
    for call in (
        lambda: db.get_memory(conn, "nope"),
        lambda: db.set_brief(conn, "nope", "x"),
        lambda: db.what_changed(conn, "nope"),
    ):
        with pytest.raises(db.DocumentNotFound):
            call()


def test_brief_routes(client):
    assert client.get("/documents/default/brief").json()["brief"] == ""
    assert client.put("/documents/default/brief", json={"brief": "Thermo notes"}).status_code == 200
    assert client.get("/documents/default/brief").json()["brief"] == "Thermo notes"
    assert client.put("/documents/default/brief", json={"brief": "x" * 4001}).status_code == 422
    assert (
        client.put("/documents/default/brief", json={"brief": "x", "extra": 1}).status_code == 422
    )
    assert client.get("/documents/nope/brief").status_code == 404
    assert client.put("/documents/nope/brief", json={"brief": "x"}).status_code == 404
    assert client.get("/documents/nope/changes").status_code == 404


def test_changes_route_mark_seen(client):
    Canvas(client, row("a", 4))
    r = client.get("/documents/default/changes", params={"since": 0, "mark_seen": True}).json()
    assert len(r["chunks"]) == 1
    assert client.get("/documents/default/changes").json()["chunks"] == []


@pytest.fixture
def api(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return json.loads(asyncio.run(server.mcp.call_tool(name, args)).content[0].text)


def test_tools_registered_and_in_instructions():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"what_changed", "set_canvas_brief"} <= names
    assert (
        "what_changed" in server.mcp.instructions and "set_canvas_brief" in server.mcp.instructions
    )


def test_brief_reaches_read_canvas(api):
    Canvas(api, row("a", 4))
    assert call("read_canvas", include_overview=False)["brief"] == ""
    call("set_canvas_brief", brief="x")
    assert call("read_canvas", include_overview=False)["brief"] == "x"


def test_what_changed_tool(api):
    Canvas(api, row("a", 4))
    assert len(call("what_changed", since=0)["chunks"]) == 1
    call("what_changed", mark_seen=True)
    assert call("what_changed")["chunks"] == []


def test_brief_tool_errors(api):
    with pytest.raises(ToolError):
        call("set_canvas_brief", brief="x" * 4001)
    with pytest.raises(ToolError):
        call("set_canvas_brief", brief="x", document_id="nope")
