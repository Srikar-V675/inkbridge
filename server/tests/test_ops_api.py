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


def own(op_id, n="1"):
    """An element id issued for this op (see ops_db.id_prefix)."""
    return f"{op_id}:{n}"


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
    r = ack(client, op["id"], [own(op["id"]), "user-a"])
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "existing_element_id", "ids": ["user-a"]}
    assert client.get(f"/ops/{op['id']}").json()["status"] == "pending"


def test_ack_with_ids_not_issued_for_the_op_is_rejected(client):
    # Not in the scene yet, but not this op's ids either: a later Reject must never reach them.
    op = write(client).json()
    r = ack(client, op["id"], ["random-new-id"])
    assert r.status_code == 422 and r.json()["detail"]["ids"] == ["random-new-id"]


def test_ack_with_new_ids_applies_and_records_them(client):
    seed(client)
    op = write(client).json()
    assert op["payload"]["id_prefix"] == f"{op['id']}:"
    ids = [own(op["id"], "1"), own(op["id"], "2")]
    r = ack(client, op["id"], ids)
    assert r.status_code == 200
    assert r.json()["status"] == "applied"
    assert r.json()["result"] == {"element_ids": ids}


def test_ack_after_autosave_accepts_the_ops_own_drafts(client):
    # Autosave may store the drafts before the ack arrives.
    seed(client)
    op = write(client).json()
    tag = {"author": "agent", "draft": True, "op_id": op["id"]}
    seed(client, [USER_A, USER_B, stroke(own(op["id"]), 0, 500, customData=tag)])
    assert ack(client, op["id"], [own(op["id"])]).status_code == 200


def test_ack_cannot_claim_a_user_element_tagged_with_this_op(client):
    # customData is written by the client, so a tag proves nothing about who made the element.
    op = write(client).json()
    tag = {"author": "agent", "draft": True, "op_id": op["id"]}
    seed(client, [stroke("user-a", 10, 20, customData=tag)])
    r = ack(client, op["id"], ["user-a"])
    assert r.status_code == 422 and r.json()["detail"]["ids"] == ["user-a"]


def test_ack_cannot_claim_ids_of_another_op(client):
    first, second = write(client, "one").json(), write(client, "two").json()
    assert ack(client, first["id"], [own(first["id"])]).status_code == 200
    r = ack(client, second["id"], [own(first["id"])])
    assert r.status_code == 422 and r.json()["detail"]["ids"] == [own(first["id"])]


def test_client_op_id_whose_prefix_is_already_in_the_scene_is_rejected(client):
    seed(client, [stroke("op-x:1", 0, 0)])
    r = write(client, op_id="op-x")
    assert r.status_code == 422 and r.json()["detail"]["ids"] == ["op-x:1"]


def test_in_lock_guard_refuses_existing_ids_on_its_own(client):
    seed(client)
    conn = db.connect()
    try:
        with pytest.raises(ops_db.ExistingElementIds):
            ops_db.create_op(conn, "default", "write_text", {"text": "user-a"})
    finally:
        conn.close()


def test_deeply_nested_payload_is_a_422_not_a_crash(client):
    seed(client)
    nested: list = ["user-a"]
    for _ in range(5000):
        nested = [nested]
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "deep": nested}})
    assert r.status_code == 422


# --- lifecycle --------------------------------------------------------------------------------


def test_full_lifecycle_and_invalid_transitions(client):
    op = write(client).json()
    assert op["status"] == "pending" and op["document_id"] == "default"
    assert client.patch(f"/ops/{op['id']}", json={"status": "accepted"}).status_code == 409
    assert ack(client, op["id"], [own(op["id"])]).status_code == 200
    assert ack(client, op["id"], [own(op["id"])]).status_code == 200  # same ack again: idempotent
    assert ack(client, op["id"], [own(op["id"], "2")]).status_code == 409  # different ids: conflict
    r = client.patch(f"/ops/{op['id']}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.patch(f"/ops/{op['id']}", json={"status": "accepted"}).status_code == 409


def test_failed_records_the_error(client):
    op = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": "nope"}}).json()
    r = client.patch(f"/ops/{op['id']}", json={"status": "failed", "error": "parse error"})
    assert r.status_code == 200 and r.json()["error"] == "parse error"
    assert ack(client, op["id"], [own(op["id"])]).status_code == 409


def test_delivered_ops_can_be_applied_or_expire(client):
    a, b = write(client, "a").json(), write(client, "b").json()
    conn = db.connect()
    try:
        ops_db.mark_delivered(conn, a["id"])
        ops_db.mark_delivered(conn, b["id"])
    finally:
        conn.close()
    assert client.get(f"/ops/{a['id']}").json()["status"] == "delivered"
    assert ack(client, a["id"], [own(a["id"])]).status_code == 200
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
        ack(c, b["id"], [own(b["id"])])
        conn = db.connect()
        try:
            ops_db.mark_delivered(conn, c3["id"])  # pushed, then the browser went away
        finally:
            conn.close()
    with TestClient(app) as c:  # a fresh lifespan on the same file, as after an API restart
        pending = c.get(OPS, params={"status": "pending"}).json()["ops"]
        assert [o["id"] for o in pending] == [a["id"]]
        assert pending[0]["payload"]["text"] == "a"
        replay = c.get(OPS, params={"status": "pending,delivered"}).json()["ops"]
        assert [o["id"] for o in replay] == [a["id"], c3["id"]]
        everything = c.get(OPS).json()["ops"]
        assert [o["id"] for o in everything] == [a["id"], b["id"], c3["id"]]
        assert c.get(OPS, params={"status": "bogus"}).status_code == 422


# --- placement --------------------------------------------------------------------------------


def _anchor_region(element_ids):
    """The chunk the scene save made for exactly these elements (INK-031 owns auto rows)."""
    conn = db.connect()
    try:
        chunks = db.list_regions(conn, "default", chunks=True, limit=500)
    finally:
        conn.close()
    (rid,) = [c["id"] for c in chunks if sorted(c["element_ids"]) == sorted(element_ids)]
    return rid


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
    ack(client, op["id"], [own(op["id"])])
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op["id"],)).fetchone()
    finally:
        conn.close()
    assert row["document_id"] == "default" and row["created_at"]
    assert json.loads(row["result_json"]) == {"element_ids": [own(op["id"])]}


def test_resolved_ops_release_their_spot(client):
    first = write(client).json()
    assert first["payload"]["placement"] == {"x": 0, "y": 0}
    client.patch(f"/ops/{first['id']}", json={"status": "expired"})
    assert write(client).json()["payload"]["placement"] == {"x": 0, "y": 0}


def test_anchored_diagram_is_placed_beside_the_chunk_when_there_is_room(client):
    seed(client, [USER_A])
    rid = _anchor_region(["user-a"])
    payload = {"mermaid": "flowchart TD\nA-->B", "anchor": rid}
    op = client.post(OPS, json={"type": "draw_diagram", "payload": payload}).json()
    box = bbox_of([USER_A])
    assert op["payload"]["placement"] == {"x": box["x"] + box["width"] + 40, "y": box["y"]}


def test_reack_with_the_same_ids_in_another_order_is_idempotent(client):
    op = write(client).json()
    ids = [own(op["id"], "1"), own(op["id"], "2")]
    assert ack(client, op["id"], ids).status_code == 200
    r = ack(client, op["id"], list(reversed(ids)))
    assert r.status_code == 200 and r.json()["result"] == {"element_ids": ids}
    assert ack(client, op["id"], ids[:1]).status_code == 409  # a different set still conflicts


def test_placement_avoids_the_corners_of_rotated_ink(client):
    import math

    from inkbridge.placement import estimate_size

    # A long thin bar turned upright: its unrotated box is flat, the real shape is tall.
    bar = {
        "id": "bar",
        "type": "rectangle",
        "x": -180,
        "y": 0,
        "width": 400,
        "height": 10,
        "angle": math.pi / 2,
    }
    seed(client, [bar])
    payload = {"text": "hello world, a longer note"}
    op = client.post(OPS, json={"type": "write_text", "payload": payload}).json()
    box = _op_box(op, estimate_size("write_text", payload))
    cx, cy = bar["x"] + bar["width"] / 2, bar["y"] + bar["height"] / 2
    c, s = math.cos(bar["angle"]), math.sin(bar["angle"])
    corners = [
        (cx + (px - cx) * c - (py - cy) * s, cy + (px - cx) * s + (py - cy) * c)
        for px in (bar["x"], bar["x"] + bar["width"])
        for py in (bar["y"], bar["y"] + bar["height"])
    ]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    real = {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
    assert not overlaps(box, real), (box, real)
