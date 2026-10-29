"""MCP draw_diagram (INK-044): creates a draft op and waits, bounded, for the browser's ack."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient

FLOW = "flowchart TD\n  A[Start] --> B[Done]"


class Browser:
    """Stands in for the web app: called on each poll sleep, it acts on the newest op."""

    def __init__(self, client, action=None, after=1):
        self.client, self.action, self.after, self.sleeps = client, action, after, 0

    def __call__(self, _seconds):
        self.sleeps += 1
        if self.action is None or self.sleeps != self.after:
            return
        (op,) = self.client.get("/documents/default/ops").json()["ops"][-1:]
        self.action(self.client, op)


def apply(client, op):
    ids = [f"{op['payload']['id_prefix']}{i}" for i in (1, 2, 3)]
    client.patch(f"/ops/{op['id']}", json={"status": "applied", "element_ids": ids})


def fail(client, op):
    client.patch(
        f"/ops/{op['id']}",
        json={"status": "failed", "error": "Mermaid could not be parsed: Parse error on line 2"},
    )


@pytest.fixture
def tool(client, monkeypatch):
    server.set_client(ApiClient(client))
    now = [0.0]
    monkeypatch.setattr(server, "_clock", lambda: now[0])

    def run(action=None, after=1, **args):
        browser = Browser(client, action, after)

        def sleep(seconds):
            now[0] += seconds
            browser(seconds)

        monkeypatch.setattr(server, "_sleep", sleep)
        return asyncio.run(server.mcp.call_tool("draw_diagram", {"mermaid": FLOW, **args}))

    yield run
    server.set_client(None)


def test_applied_diagram_returns_its_element_count(tool, client):
    out = json.loads(tool(apply, after=2).content[0].text)
    (op,) = client.get("/documents/default/ops").json()["ops"]
    assert out == {"op_id": op["id"], "status": "applied", "element_count": 3}
    assert op["type"] == "draw_diagram" and op["payload"]["mermaid"] == FLOW


def test_invalid_mermaid_reported_by_the_browser_is_a_tool_error(tool, client):
    with pytest.raises(ToolError, match="Mermaid could not be parsed: Parse error on line 2"):
        tool(fail)
    (op,) = client.get("/documents/default/ops").json()["ops"]
    assert op["status"] == "failed" and op["result"] is None  # no partial elements recorded


def test_no_browser_times_out_expires_the_op_and_says_to_open_the_canvas(tool, client):
    with pytest.raises(
        ToolError, match=r"No browser drew the diagram within 3 s.*\?canvas=default"
    ):
        tool(wait_seconds=3)
    (op,) = client.get("/documents/default/ops").json()["ops"]
    assert op["status"] == "expired"  # a browser that connects later will not draw it


def test_waits_no_longer_than_asked(tool, client):
    with pytest.raises(ToolError):
        tool(wait_seconds=2)
    assert server._clock() <= 2 + server.POLL_SECONDS


def test_browser_finishing_as_the_wait_ends_still_counts(tool, client, monkeypatch):
    # The ack lands between the last poll and the expiry PATCH: the PATCH conflicts, the op is
    # re-read and reported as applied rather than as a timeout.
    real = ApiClient.set_op_status

    def late_ack(self, op_id, status):
        op = client.get(f"/ops/{op_id}").json()
        apply(client, op)
        return real(self, op_id, status)

    monkeypatch.setattr(ApiClient, "set_op_status", late_ack)
    out = json.loads(tool(wait_seconds=1).content[0].text)
    assert out["status"] == "applied" and out["element_count"] == 3


@pytest.mark.parametrize("source", ["sequenceDiagram\n  A->>B: hi", "classDiagram\n  A <|-- B"])
def test_non_flowcharts_are_refused_before_any_op_exists(tool, client, source):
    with pytest.raises(ToolError, match="only Mermaid flowcharts are supported"):
        tool(mermaid=source)
    assert client.get("/documents/default/ops").json()["ops"] == []


def test_unknown_anchor_and_document_are_tool_errors(tool):
    with pytest.raises(ToolError, match="anchor_not_found|anchor"):
        tool(anchor="no-such-chunk")
    with pytest.raises(ToolError, match="Not found"):
        tool(document_id="nope")


def test_existing_element_ids_cannot_be_smuggled_in(tool, client):
    client.put("/documents/default/scene", json={"base_version": 0, "elements": [{"id": "ink"}]})
    with pytest.raises(ToolError, match="existing_element_id"):
        tool(anchor="ink")
    assert client.get("/documents/default/ops").json()["ops"] == []


def test_the_tool_is_registered_with_flowchart_only_in_its_description():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert "draw_diagram" in tools
    assert "FLOWCHART" in tools["draw_diagram"].description
    assert "browser" in tools["draw_diagram"].description
