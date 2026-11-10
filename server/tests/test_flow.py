"""Drafts answer in place (INK-201, decision 0116)."""

import json
from contextlib import closing

from inkbridge import db
from inkbridge.agent import flow
from inkbridge.agent.placement import gap_for
from inkbridge.db import drafts
from tests.test_drafts import accept, els, measure, post
from tests.test_ops_api import OPS, _anchor_region, _question, seed, stroke, write

ANCHOR = {"x": 100.0, "y": 50.0, "width": 200.0, "height": 40.0}


def test_answer_lead():
    assert flow.answer_lead("hi") == "Answer: hi"
    assert flow.answer_lead("Answer: x") == "Answer: x"
    assert flow.answer_lead("answer:x") == "answer:x"


def test_question_answer_gets_lead_and_plain_text_does_not(client):
    seed(client)
    q = _question(client)
    r = write(client, payload={"text": "forty-two", "question_id": q})
    assert r.json()["payload"]["text"] == "Answer: forty-two"
    r = write(client, "plain")
    assert r.json()["payload"]["text"] == "plain"


def test_arrow_below_and_right():
    below = flow.arrow_for("op1:", ANCHOR, {"x": 100, "y": 130}, (300, 60))
    assert below["id"] == "op1:flow-arrow" and below["strokeStyle"] == "dashed"
    assert (below["x"], below["y"]) == (200, 90)  # middle of the anchor's bottom edge
    assert below["points"] == [[0, 0], [0, 40]]
    right = flow.arrow_for("op1:", ANCHOR, {"x": 340, "y": 50}, (300, 60))
    assert (right["x"], right["y"]) == (300, 70) and right["points"] == [[0, 0], [40, 0]]


def test_arrow_none_for_other_positions_and_tiny_gaps():
    assert flow.arrow_for("p:", ANCHOR, {"x": -500, "y": -500}, (10, 10)) is None
    assert flow.arrow_for("p:", ANCHOR, {"x": 100, "y": 94}, (10, 10)) is None


def _anchored(client, ids=("user-a",), text="hello"):
    rid = _anchor_region(list(ids))
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": text, "anchor": rid}})
    assert r.status_code == 201
    return r.json(), rid


def test_measure_with_anchor_adds_one_flow_arrow(client):
    seed(client)
    op, rid = _anchored(client)
    got = measure(client, op, width=120, height=30)
    arrows = [e for e in got["elements"] if e["id"] == f"{op['id']}:flow-arrow"]
    assert len(arrows) == 1
    assert arrows[0]["customData"] == {"author": "agent", "op_id": op["id"], "draft": True}
    assert (got["box"]["width"], got["box"]["height"]) == (120, 30)
    with closing(db.connect()) as conn:
        bbox = json.loads(conn.execute("SELECT bbox FROM regions WHERE id=?", (rid,)).fetchone()[0])
    assert arrows[0]["y"] == bbox["y"] + bbox["height"]


def test_measure_without_anchor_has_no_arrow(client):
    seed(client)
    got = measure(client, post(client))
    assert not [e for e in got["elements"] if "flow-arrow" in e["id"]]


def test_client_flow_arrow_id_gets_no_second_arrow(client):
    seed(client)
    op, _ = _anchored(client)
    mine = els(op["id"]) + [{**els(op["id"])[0], "id": f"{op['id']}:flow-arrow", "type": "arrow"}]
    with closing(db.connect()) as conn:
        got = drafts.measure_op(conn, op["id"], mine, 120, 30)
    assert [e["id"] for e in got["elements"]].count(f"{op['id']}:flow-arrow") == 1


def test_two_anchors_two_drafts_by_their_own_question(client):
    seed(client, [stroke("a", 0, 0, 200, 40), stroke("b", 3000, 0, 200, 40)])
    boxes = []
    for sid in ("a", "b"):
        op, rid = _anchored(client, [sid])
        got = measure(client, op, width=200, height=60)
        with closing(db.connect()) as conn:
            ab = json.loads(
                conn.execute("SELECT bbox FROM regions WHERE id=?", (rid,)).fetchone()[0]
            )
        fs = op["payload"]["font_size"]
        assert 0 <= got["box"]["y"] - (ab["y"] + ab["height"]) <= max(1.25 * fs, gap_for(fs))
        assert got["box"]["y"] >= ab["y"] + ab["height"] + gap_for(fs) - 1
        boxes.append(got["box"])
    a, b = boxes
    assert a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]


def test_accepted_arrow_does_not_merge_question_and_answer_chunks(client):
    seed(client, [stroke("q", 0, 0, 200, 40)])
    qchunk = client.get("/documents/default/regions?chunks=true").json()
    (qc,) = qchunk
    op, _ = _anchored(client, ["q"], text="Answer: forty-two")
    measure(client, op, width=200, height=40)
    assert accept(client, op["id"]).status_code == 200
    chunks = client.get("/documents/default/regions?chunks=true").json()
    active = [c for c in chunks if c.get("status", "active") == "active"]
    assert len(active) == 2
    user = next(c for c in active if "q" in c["element_ids"])
    assert user["element_ids"] == ["q"] == qc["element_ids"]
    agent = next(c for c in active if c is not user)
    assert f"{op['id']}:flow-arrow" not in user["element_ids"]
    assert all(i.startswith(f"{op['id']}:") for i in agent["element_ids"])
