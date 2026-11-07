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
