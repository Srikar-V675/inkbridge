"""Diagram objects and revisions (INK-140, decision 0100)."""

import json
from contextlib import closing

import pytest

from inkbridge import db
from inkbridge.db import diagrams, drafts
from inkbridge.db import ops as ops_db
from tests.test_chunk_persistence import Canvas, row
from tests.test_detectors import chunks, of_kind
from tests.test_drafts import accept, els, measure, scene_rows
from tests.test_ops_api import OPS, SCENE, seed
from tests.test_search import recognise

FLOW = "flowchart TD\n A-->B"
GRAPH = json.dumps(
    {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "shape": "diamond"}],
     "edges": [{"from": "a", "to": "b"}]}
)


def draw(client, source=FLOW, kind="mermaid", **extra):
    return client.post(
        OPS,
        json={"type": "draw_diagram", "payload": {"source": source, "source_kind": kind, **extra}},
    )


def diagram(did):
    with closing(db.connect()) as conn:
        return diagrams.get(conn, did)


def test_draw_diagram_creates_diagram_row(client):
    r = draw(client)
    assert r.status_code == 201
    op = r.json()
    assert op["diagram_id"] and op["revises"] is None
    d = diagram(op["diagram_id"])
    assert (d["version"], d["current_op"], d["source"]) == (0, op["id"], FLOW)


def test_legacy_mermaid_key_still_works(client):
    r = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": FLOW}})
    assert r.status_code == 201
    assert r.json()["payload"]["source"] == FLOW and r.json()["payload"]["source_kind"] == "mermaid"


@pytest.mark.parametrize(
    "source",
    [
        "{not json",
        json.dumps({"nodes": [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]}),
        json.dumps({"nodes": [{"id": "a", "label": "x"}], "edges": [{"from": "a", "to": "z"}]}),
        FLOW,
    ],
)
def test_graph_source_validated(client, source):
    r = draw(client, source, "graph")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_graph"
    assert draw(client, GRAPH, "graph").status_code == 201


def test_from_chunks_must_be_chunks_of_this_canvas(client):
    r = draw(client, from_chunks=["nope"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "chunk_not_found"


def test_node_map_from_measure(client):
    op = draw(client).json()
    tagged = els(op["id"], 2)
    tagged[0]["customData"] = {"node": "a"}
    tagged[1]["containerId"] = tagged[0]["id"]
    with closing(db.connect()) as conn:
        drafts.measure_op(conn, op["id"], tagged, 120, 30)
        got = ops_db.get_op(conn, op["id"])
    assert got["payload"]["node_map"] == {"a": [tagged[0]["id"], tagged[1]["id"]]}


def test_edit_needs_accepted_diagram(client):
    op = draw(client).json()
    r = draw(client, diagram_id=op["diagram_id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "diagram_not_accepted"
    measure(client, op)
    assert draw(client, diagram_id=op["diagram_id"]).status_code == 409  # placed is not accepted
    r = draw(client, diagram_id="nope")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "diagram_not_found"


# --- revisions: Accept replaces only what the user has not touched --------------------------------


def accepted_diagram(client, n=3):
    seed(client)
    a = draw(client).json()
    measure(client, a, n=n)
    assert accept(client, a["id"]).status_code == 200
    return a


def revise(client, did, n=2):
    b = draw(client, GRAPH, "graph", diagram_id=did).json()
    measure(client, b, n=n)
    return b


def test_revision_accept_replaces_unchanged_keeps_user_changed(client):
    a = accepted_diagram(client)
    mine = {e["id"]: e for e in scene_rows(a["id"])}
    mid = f"{a['id']}:2"
    edited = {**mine[mid], "version": mine[mid]["version"] + 1, "x": 999}
    r = client.post("/documents/default/elements", json={"device": "d1", "batch": 1, "elements": [edited]})
    assert r.status_code == 200
    b = draw(client, GRAPH, "graph", diagram_id=a["diagram_id"]).json()
    assert b["revises"] == a["id"]
    measure(client, b, n=2)
    assert accept(client, b["id"]).status_code == 200
    old = {e["id"]: e for e in scene_rows(a["id"])}
    assert old[f"{a['id']}:1"]["isDeleted"] and old[f"{a['id']}:3"]["isDeleted"]
    assert old[f"{a['id']}:1"]["version"] == mine[f"{a['id']}:1"]["version"] + 1
    assert not old[mid].get("isDeleted") and old[mid]["x"] == 999
    assert not any(e.get("isDeleted") for e in scene_rows(b["id"]))
    live = {e["id"] for e in client.get(SCENE).json()["elements"] if not e.get("isDeleted")}
    assert {"user-a", "user-b"} <= live


def test_revision_accept_commits_diagram_row(client):
    a = accepted_diagram(client)
    d = diagram(a["diagram_id"])
    assert (d["version"], d["current_op"]) == (1, a["id"])
    b = revise(client, a["diagram_id"])
    assert accept(client, b["id"]).status_code == 200
    d = diagram(a["diagram_id"])
    assert (d["version"], d["current_op"], d["source_kind"]) == (2, b["id"], "graph")
    assert accept(client, b["id"]).status_code == 200
    assert diagram(a["diagram_id"])["version"] == 2


def test_rejected_revision_leaves_diagram(client):
    a = accepted_diagram(client)
    b = revise(client, a["diagram_id"])
    assert client.post(f"/ops/{b['id']}/reject").status_code == 200
    d = diagram(a["diagram_id"])
    assert (d["version"], d["current_op"]) == (1, a["id"])
    assert draw(client, GRAPH, "graph", diagram_id=a["diagram_id"]).status_code == 201


def test_unaccept_of_revision_refused(client):
    a = accepted_diagram(client)
    b = revise(client, a["diagram_id"])
    accept(client, b["id"])
    r = client.post(f"/ops/{b['id']}/unaccept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "window_closed"


# --- stale_diagram offers ---------------------------------------------------------------------


def accepted_from(client, chunk):
    op = draw(client, from_chunks=[chunk["id"]]).json()
    measure(client, op)
    assert accept(client, op["id"]).status_code == 200
    return op


def test_stale_diagram_when_reading_changes(client):
    _, (c,) = chunks(client, "plan A")
    op = accepted_from(client, c)
    assert of_kind("stale_diagram") == []
    recognise(c, "plan B")
    (found,) = of_kind("stale_diagram")
    assert found.anchor == c["id"]
    assert found.payload["action"] == "diagram" and found.payload["diagram"] == op["diagram_id"]


def test_moved_ink_raises_nothing(client):
    canvas, (c,) = chunks(client, "plan A")
    accepted_from(client, c)
    for e in canvas.elements:  # same ink 40 px right: content hash same, absolute position changed
        e["x"] += 40
    canvas.put()
    moved = canvas.chunk_of("r00")
    assert moved["text_hash"] == c["text_hash"]
    recognise(moved, "plan A")
    assert of_kind("stale_diagram") == []


def test_unaccepted_diagram_never_stale(client):
    _, (c,) = chunks(client, "plan A")
    op = draw(client, from_chunks=[c["id"]]).json()
    measure(client, op)
    recognise(c, "plan B")
    assert of_kind("stale_diagram") == []


def test_no_baseline_no_offer(client):
    _, (c,) = chunks(client, None)
    accepted_from(client, c)
    recognise(c, "plan B")
    assert of_kind("stale_diagram") == []
