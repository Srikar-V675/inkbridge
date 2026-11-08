"""Mark-up as instruction (INK-141, decision 0102)."""

import asyncio
import io
import json
from contextlib import closing

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image

from inkbridge import db
from inkbridge.agent import detectors, markup
from inkbridge.db import ops as ops_db
from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_detectors import of_kind
from tests.test_diagrams import GRAPH, accept, accepted_diagram, diagram, draw, measure
from tests.test_ops_api import OPS


def ink(client, i=1, x=40, y=360, **extra):
    e = {
        "id": f"ink-{i}",
        "type": "freedraw",
        "x": x,
        "y": y,
        "width": 60,
        "height": 20,
        "points": [[0, 0], [60, 20]],
        "pressures": [0.5, 0.5],
        "simulatePressure": False,
        "version": 1,
        "versionNonce": 1,
        "isDeleted": False,
        **extra,
    }
    r = client.post(
        "/documents/default/elements", json={"device": "d1", "batch": i, "elements": [e]}
    )
    assert r.status_code == 200
    return e


def sql(query, *args):
    with closing(db.connect()) as conn:
        conn.execute(query, args)
        conn.commit()


def row(eid):
    with closing(db.connect()) as conn:
        r = conn.execute(
            "SELECT json, is_deleted, updated_at FROM scene_elements WHERE id=?", (eid,)
        ).fetchone()
        return dict(r)


def accept_time(op):
    with closing(db.connect()) as conn:
        return ops_db.get_op(conn, op["id"])["result"]["at"]


def run_detectors():
    with closing(db.connect()) as conn:
        detectors.run(conn, "default")


def offers(client):
    return client.get("/documents/default/offers").json()["offers"]


# --- detector ---------------------------------------------------------------------------------


def test_markup_offer_for_ink_over_accepted_diagram(client):
    op = accepted_diagram(client)
    ink(client)
    (found,) = of_kind("markup")
    with closing(db.connect()) as conn:
        agent = [
            c
            for c in db.list_regions(conn, "default", chunks=True, status="active")
            if c["source"] == "agent"
        ]
    assert [c["id"] for c in agent] and found.anchor == agent[0]["id"]
    assert found.payload["diagram"] == op["diagram_id"]
    assert found.payload["markup"] is True
    assert found.payload["key"] == f"{op['diagram_id']}:ink-1"
    assert found.reason == "Apply mark-up?"


def test_no_offer_for_ink_before_accept(client):
    from tests.test_ops_api import seed

    seed(client)
    ink(client)
    sql("UPDATE scene_elements SET updated_at='2000-01-01T00:00:00+00:00' WHERE id='ink-1'")
    a = draw(client).json()
    measure(client, a, n=3)
    assert accept(client, a["id"]).status_code == 200
    assert of_kind("markup") == []


def test_no_offer_for_ink_far_away(client):
    accepted_diagram(client)
    ink(client, x=5000)
    assert of_kind("markup") == []


def test_no_offer_outside_window(client):
    op = accepted_diagram(client)
    ink(client)
    late = markup.datetime.fromisoformat(accept_time(op)) + markup.timedelta(hours=2)
    sql("UPDATE scene_elements SET updated_at=? WHERE id='ink-1'", late.isoformat())
    assert of_kind("markup") == []


def test_agent_elements_are_not_markup(client):
    a = accepted_diagram(client)
    b = draw(client).json()
    measure(client, b, n=3)
    assert accept(client, b["id"]).status_code == 200
    # agent elements of b overlap a's box, but they are agent-authored: no mark-up offers
    assert [c for c in of_kind("markup") if c.payload["diagram"] == a["diagram_id"]] == []


def test_no_offer_for_unaccepted_draft(client):
    from tests.test_ops_api import seed

    seed(client)
    a = draw(client).json()
    measure(client, a, n=3)
    ink(client)
    assert of_kind("markup") == []


def test_markup_offer_dismissed_stays_dismissed(client):
    accepted_diagram(client)
    ink(client)
    run_detectors()
    (o,) = [o for o in offers(client) if o["kind"] == "markup"]
    assert client.post(f"/offers/{o['id']}/dismiss").status_code == 200
    ink(client, i=2, y=362)
    run_detectors()
    assert [o for o in offers(client) if o["kind"] == "markup" and o["status"] != "dismissed"] == []


# --- task mode and crop endpoints ---------------------------------------------------------------


def markup_task(client):
    op = accepted_diagram(client)
    ink(client)
    run_detectors()
    (o,) = [o for o in offers(client) if o["kind"] == "markup"]
    assert client.post(f"/offers/{o['id']}/tap").status_code == 200
    (t,) = [t for t in client.get("/documents/default/tasks").json()["tasks"] if t["mode"] == "markup"]
    return op, t


def test_tap_markup_offer_makes_markup_task(client):
    op, t = markup_task(client)
    assert t["allowed_op_types"] == ["draw_diagram"] and t["op_limit"] == 1
    assert t["input"]["payload"]["diagram"] == op["diagram_id"]


def test_markup_endpoint_lists_ink(client):
    op = accepted_diagram(client)
    did = op["diagram_id"]
    r = client.get(f"/documents/default/diagrams/{did}/markup")
    assert r.status_code == 200 and r.json()["ink_ids"] == []
    ink(client)
    j = client.get(f"/documents/default/diagrams/{did}/markup").json()
    assert j["ink_ids"] == ["ink-1"] and j["diagram_id"] == did
    assert j["version"] == 1 and j["source_kind"] == "mermaid" and j["source"]
    assert len(j["box"]) == 4
    assert client.get("/documents/default/diagrams/nope/markup").status_code == 404
    assert client.get(f"/documents/other/diagrams/{did}/markup").status_code == 404


def test_markup_png_is_png_with_ink_colour(client):
    op = accepted_diagram(client)
    did = op["diagram_id"]
    ink(client, strokeColor="#000000")
    r = client.get(f"/documents/default/diagrams/{did}/markup.png")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    want = (0xD3, 0x2F, 0x2F)
    assert any(
        all(abs(a - b) < 40 for a, b in zip(p, want, strict=True)) for p in img.getdata()
    )
    assert client.get("/documents/default/diagrams/nope/markup.png").status_code == 404


def test_markup_task_limited_to_one_draft(client):
    op, t = markup_task(client)
    did = op["diagram_id"]
    assert client.post(f"/tasks/{t['id']}/claim", json={"claimed_by": "t"}).status_code == 200

    def post(type_="draw_diagram"):
        payload = {"source": GRAPH, "source_kind": "graph", "diagram_id": did, "task_id": t["id"]}
        if type_ == "write_text":
            payload = {"text": "x", "task_id": t["id"]}
        return client.post(OPS, json={"type": type_, "payload": payload})

    assert post().status_code == 201
    r = post()
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_op_limit"
    assert post("write_text").json()["detail"]["code"] == "task_mode"


# --- MCP ------------------------------------------------------------------------------------------


@pytest.fixture
def mcp_client(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def test_mcp_get_markup(mcp_client):
    op = accepted_diagram(mcp_client)
    ink(mcp_client)
    parts = asyncio.run(
        server.mcp.call_tool("get_markup", {"diagram_id": op["diagram_id"]})
    ).content
    assert json.loads(parts[0].text)["ink_ids"] == ["ink-1"]
    assert parts[1].type == "image"
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool("get_markup", {"diagram_id": "nope"}))


# --- end to end -----------------------------------------------------------------------------------


def test_markup_end_to_end(client):
    a, t = markup_task(client)
    mine = row("ink-1")
    assert client.post(f"/tasks/{t['id']}/claim", json={"claimed_by": "t"}).status_code == 200
    did = a["diagram_id"]
    assert client.get(f"/documents/default/diagrams/{did}/markup").json()["ink_ids"] == ["ink-1"]
    assert client.get(f"/documents/default/diagrams/{did}/markup.png").content.startswith(
        b"\x89PNG"
    )
    body = {"source": GRAPH, "source_kind": "graph", "diagram_id": did, "task_id": t["id"]}
    b = client.post(OPS, json={"type": "draw_diagram", "payload": body}).json()
    measure(client, b, n=2)
    assert accept(client, b["id"]).status_code == 200
    with closing(db.connect()) as conn:
        rows = conn.execute("SELECT id, is_deleted FROM scene_elements").fetchall()
    old = [r["is_deleted"] for r in rows if r["id"].startswith(f"{a['id']}:")]
    new = [r["is_deleted"] for r in rows if r["id"].startswith(f"{b['id']}:")]
    assert old and all(old) and new and not any(new)
    assert diagram(did)["version"] == 2
    assert row("ink-1") == mine and mine["is_deleted"] == 0
    assert of_kind("markup") == []
    r = client.post(OPS, json={"type": "draw_diagram", "payload": body})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_op_limit"
