"""Agent ops queue (INK-041). Invariant N1: an agent path can only add elements, never edit ink."""

import json

import pytest
from fastapi.testclient import TestClient

from inkbridge import db
from inkbridge.api import app
from inkbridge.db import ops as ops_db
from inkbridge.placement import overlaps
from inkbridge.regions import bbox_of

SCENE = "/documents/default/scene"
OPS = "/documents/default/ops"


def stroke(eid, x, y, w=30, h=40, **extra):
    return {
        "id": eid,
        "type": "freedraw",
        "x": x,
        "y": y,
        "points": [[0, 0], [w, h]],
        "pressures": [0.3, 0.6],
        "simulatePressure": False,
        **extra,
    }


USER_A = stroke("user-a", 10, 20)
USER_B = stroke("user-b", 400, 300, w=50, h=10)


def seed(client, elements=(USER_A, USER_B)):
    version = client.get(SCENE).json()["version"]
    r = client.put(SCENE, json={"base_version": version, "elements": list(elements)})
    assert r.status_code == 200


def write(client, text="hello", **extra):
    return client.post(OPS, json={"type": "write_text", "payload": {"text": text}, **extra})


def ack(client, op_id, ids):
    return client.patch(f"/ops/{op_id}", json={"status": "applied", "element_ids": ids})


# --- invariant N1: payloads never reference existing ink ---------------------------------------


def test_payload_naming_an_existing_element_id_is_rejected(client):
    seed(client)
    r = client.post(
        OPS, json={"type": "write_text", "payload": {"text": "x", "element_ids": ["user-a"]}}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "existing_element_id"
    assert r.json()["detail"]["ids"] == ["user-a"]
    assert client.get(OPS).json()["ops"] == []


def test_existing_id_in_an_allowed_field_is_rejected_too(client):
    # The schema accepts this payload, so only the existing-id check can stop it.
    seed(client)
    r = write(client, text="user-b")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "existing_element_id"
    r = client.post(
        OPS,
        json={"type": "draw_diagram", "payload": {"mermaid": "flowchart TD", "anchor": "user-a"}},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "existing_element_id"


def test_deleted_elements_still_count_as_existing(client):
    seed(client, [stroke("gone", 0, 0, isDeleted=True)])
    r = write(client, text="gone")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "existing_element_id"


@pytest.mark.parametrize(
    "op_type", ["delete", "update", "edit", "delete_element", "update_element", "move", ""]
)
def test_only_write_text_and_draw_diagram_exist(client, op_type):
    seed(client)
    # A harmless payload, so only the type check can refuse it.
    r = client.post(OPS, json={"type": op_type, "payload": {"text": "x"}})
    assert r.status_code == 422
    assert client.get(OPS).json()["ops"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"text": "x", "elements": [{"type": "text"}]},
        {"text": "x", "placement": {"x": 0, "y": 0}},
        {"mermaid": "flowchart TD"},
    ],
)
def test_write_text_payload_is_strict(client, payload):
    r = client.post(OPS, json={"type": "write_text", "payload": payload})
    assert r.status_code == 422


def test_unknown_document_is_404(client):
    r = client.post("/documents/nope/ops", json={"type": "write_text", "payload": {"text": "x"}})
    assert r.status_code == 404


def test_unknown_anchor_is_422(client):
    r = client.post(
        OPS, json={"type": "write_text", "payload": {"text": "x", "anchor": "no-such-chunk"}}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "anchor_not_found"


# --- invariant N1: the browser's ack ids must be new ---------------------------------------------


def test_ack_with_an_existing_user_element_id_is_rejected(client):
    seed(client)
    op = write(client).json()
    r = ack(client, op["id"], ["new-1", "user-a"])
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "existing_element_id", "ids": ["user-a"]}
    assert client.get(f"/ops/{op['id']}").json()["status"] == "pending"


def test_ack_with_new_ids_applies_and_records_them(client):
    seed(client)
    op = write(client).json()
    r = ack(client, op["id"], ["new-1", "new-2"])
    assert r.status_code == 200
    assert r.json()["status"] == "applied"
    assert r.json()["result"] == {"element_ids": ["new-1", "new-2"]}


def test_ack_after_autosave_accepts_the_ops_own_drafts(client):
    # Autosave may store the drafts before the ack arrives; they are tagged with this op.
    seed(client)
    op = write(client).json()
    draft = stroke(
        "new-1", 0, 500, customData={"author": "agent", "draft": True, "op_id": op["id"]}
    )
    seed(client, [USER_A, USER_B, draft])
    assert ack(client, op["id"], ["new-1"]).status_code == 200


def test_ack_cannot_claim_a_user_element_tagged_for_another_op(client):
    seed(client)
    op = write(client).json()
    other = stroke("new-1", 0, 500, customData={"author": "agent", "draft": True, "op_id": "zzz"})
    seed(client, [USER_A, USER_B, other])
    r = ack(client, op["id"], ["new-1"])
    assert r.status_code == 422 and r.json()["detail"]["ids"] == ["new-1"]


def test_ack_cannot_claim_ids_of_another_op(client):
    seed(client)
    first, second = write(client, "one").json(), write(client, "two").json()
    assert ack(client, first["id"], ["new-1"]).status_code == 200
    r = ack(client, second["id"], ["new-1"])
    assert r.status_code == 422 and r.json()["detail"]["ids"] == ["new-1"]


# --- lifecycle --------------------------------------------------------------------------------


def test_full_lifecycle_and_invalid_transitions(client):
    op = write(client).json()
    assert op["status"] == "pending" and op["document_id"] == "default"
    assert client.patch(f"/ops/{op['id']}", json={"status": "accepted"}).status_code == 409
    assert ack(client, op["id"], ["n1"]).status_code == 200
    assert ack(client, op["id"], ["n1"]).status_code == 200  # same ack again: idempotent
    assert ack(client, op["id"], ["n2"]).status_code == 409  # different ids: conflict
    r = client.patch(f"/ops/{op['id']}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.patch(f"/ops/{op['id']}", json={"status": "accepted"}).status_code == 409


def test_failed_records_the_error(client):
    op = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": "nope"}}).json()
    r = client.patch(f"/ops/{op['id']}", json={"status": "failed", "error": "parse error"})
    assert r.status_code == 200 and r.json()["error"] == "parse error"
    assert ack(client, op["id"], ["n1"]).status_code == 409


def test_delivered_ops_can_be_applied_or_expire(client):
    a, b = write(client, "a").json(), write(client, "b").json()
    conn = db.connect()
    try:
        ops_db.mark_delivered(conn, a["id"])
        ops_db.mark_delivered(conn, b["id"])
    finally:
        conn.close()
    assert client.get(f"/ops/{a['id']}").json()["status"] == "delivered"
    assert ack(client, a["id"], ["n1"]).status_code == 200
    assert client.patch(f"/ops/{b['id']}", json={"status": "expired"}).json()["status"] == "expired"


def test_patch_cannot_set_pending_or_delivered(client):
    op = write(client).json()
    for status in ("pending", "delivered"):
        assert client.patch(f"/ops/{op['id']}", json={"status": status}).status_code == 422


def test_unknown_op_is_404(client):
    assert client.get("/ops/missing").status_code == 404
    assert client.patch("/ops/missing", json={"status": "rejected"}).status_code == 404


def test_post_is_idempotent_by_op_id(client):
    r1 = write(client, op_id="op-abc")
    r2 = write(client, op_id="op-abc")
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert len(client.get(OPS).json()["ops"]) == 1
    assert write(client, text="other", op_id="op-abc").status_code == 409


def test_ops_endpoint_without_document_defaults_to_default(client):
    r = client.post("/ops", json={"type": "write_text", "payload": {"text": "x"}})
    assert r.status_code == 201 and r.json()["document_id"] == "default"


def test_ops_persist_across_restart_and_list_pending_for_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "restart.db"))
    with TestClient(app) as c:
        a, b, c3 = (write(c, t).json() for t in ("a", "b", "c"))
        ack(c, b["id"], ["n1"])
    with TestClient(app) as c:  # a fresh lifespan on the same file, as after an API restart
        pending = c.get(OPS, params={"status": "pending"}).json()["ops"]
        assert [o["id"] for o in pending] == [a["id"], c3["id"]]
        assert pending[0]["payload"]["text"] == "a"
        both = c.get(OPS, params={"status": "pending,applied"}).json()["ops"]
        assert [o["id"] for o in both] == [a["id"], b["id"], c3["id"]]
        assert c.get(OPS, params={"status": "bogus"}).status_code == 422


# --- placement --------------------------------------------------------------------------------


def _anchor_region(element_ids):
    conn = db.connect()
    try:
        return db.create_region(conn, "default", element_ids, "/dev/null", created_by="auto")["id"]
    finally:
        conn.close()


def _op_box(op, size):
    p = op["payload"]["placement"]
    return {"x": p["x"], "y": p["y"], "width": size[0], "height": size[1]}


def test_empty_canvas_places_at_origin(client):
    assert write(client).json()["payload"]["placement"] == {"x": 0, "y": 0}


def test_anchored_op_goes_right_of_the_chunk(client):
    seed(client)
    rid = _anchor_region(["user-a"])
    op = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "anchor": rid}})
    assert op.status_code == 201
    box = bbox_of([USER_A])
    assert op.json()["payload"]["placement"] == {"x": box["x"] + box["width"] + 40, "y": box["y"]}


def test_stacked_ops_never_overlap_live_ink_or_each_other(client):
    from inkbridge.placement import estimate_size

    seed(client)
    rid = _anchor_region(["user-a"])
    placed = []
    for i in range(6):
        payload = {"text": f"note {i}\nsecond line"}
        if i % 2:
            payload["anchor"] = rid
        op = client.post(OPS, json={"type": "write_text", "payload": payload}).json()
        placed.append(_op_box(op, estimate_size("write_text", payload)))
    diagram = {"mermaid": "flowchart TD\nA-->B"}
    op = client.post(OPS, json={"type": "draw_diagram", "payload": diagram}).json()
    placed.append(_op_box(op, estimate_size("draw_diagram", diagram)))
    ink = [bbox_of([e]) for e in (USER_A, USER_B)]
    for i, box in enumerate(placed):
        assert not any(overlaps(box, o) for o in ink), box
        assert not any(overlaps(box, o) for o in placed[:i]), box


def test_deleted_ink_does_not_block_placement(client):
    seed(client, [stroke("gone", 0, 0, w=100, h=100, isDeleted=True)])
    assert write(client).json()["payload"]["placement"] == {"x": 0, "y": 0}


def test_ops_rows_hold_document_created_at_and_result(client):
    op = write(client).json()
    ack(client, op["id"], ["n1"])
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op["id"],)).fetchone()
    finally:
        conn.close()
    assert row["document_id"] == "default" and row["created_at"]
    assert json.loads(row["result_json"]) == {"element_ids": ["n1"]}
