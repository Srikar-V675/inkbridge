"""Agent ops queue (INK-041). Invariant N1: an agent path can only add elements, never edit ink."""

import json

import pytest
from fastapi.testclient import TestClient

from inkbridge import db
from inkbridge.agent.placement import estimate_size, gap_for, overlaps
from inkbridge.api import app
from inkbridge.canvas.chunker import proximity_threshold
from inkbridge.canvas.hashes import bbox_of
from inkbridge.db import ops as ops_db

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


def measure(client, op_id, width=120, height=30):
    from tests.test_drafts import measure as _measure

    return _measure(client, {"id": op_id}, width=width, height=height)


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


# --- invariant N1: measured ids must be new (tests/test_drafts.py) ---------------------------


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
    assert client.patch(f"/ops/{op['id']}", json={"status": "accepted"}).status_code == 422
    assert measure(client, op["id"])["status"] == "placed"
    r = client.post(f"/ops/{op['id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"/ops/{op['id']}/accept", json={}).status_code == 409


def test_failed_records_the_error(client):
    op = client.post(
        OPS, json={"type": "draw_diagram", "payload": {"mermaid": "flowchart TD\n  A[("}}
    ).json()
    r = client.patch(f"/ops/{op['id']}", json={"status": "failed", "error": "parse error"})
    assert r.status_code == 200 and r.json()["error"] == "parse error"
    with pytest.raises(ops_db.InvalidTransition):
        measure(client, op["id"])


def test_delivered_ops_can_be_placed_or_expire(client):
    a, b = write(client, "a").json(), write(client, "b").json()
    conn = db.connect()
    try:
        ops_db.mark_delivered(conn, a["id"])
        ops_db.mark_delivered(conn, b["id"])
    finally:
        conn.close()
    assert client.get(f"/ops/{a['id']}").json()["status"] == "delivered"
    assert measure(client, a["id"])["status"] == "placed"
    assert client.patch(f"/ops/{b['id']}", json={"status": "expired"}).json()["status"] == "expired"


def test_patch_cannot_set_pending_or_delivered(client):
    op = write(client).json()
    for status in ("pending", "delivered"):
        assert client.patch(f"/ops/{op['id']}", json={"status": status}).status_code == 422


def test_unknown_op_is_404(client):
    assert client.get("/ops/missing").status_code == 404
    assert client.patch("/ops/missing", json={"status": "expired"}).status_code == 404


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
        measure(c, b["id"])
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
    gap = max(
        gap_for(op.json()["payload"]["font_size"]), 1.05 * proximity_threshold([USER_A, USER_B])
    )
    assert op.json()["payload"]["placement"] == {"x": box["x"] + box["width"] + gap, "y": box["y"]}


def test_stacked_ops_never_overlap_live_ink_or_each_other(client):
    from inkbridge.agent.placement import estimate_size

    seed(client)
    rid = _anchor_region(["user-a"])
    placed = []
    for i in range(6):
        payload = {"text": f"note {i}\nsecond line"}
        if i % 2:
            payload["anchor"] = rid
        op = client.post(OPS, json={"type": "write_text", "payload": payload}).json()
        placed.append(_op_box(op, estimate_size("write_text", op["payload"])))
    diagram = {"mermaid": "flowchart TD\nA-->B"}
    op = client.post(OPS, json={"type": "draw_diagram", "payload": diagram}).json()
    placed.append(_op_box(op, estimate_size("draw_diagram", op["payload"])))
    ink = [bbox_of([e]) for e in (USER_A, USER_B)]
    for i, box in enumerate(placed):
        assert not any(overlaps(box, o) for o in ink), box
        assert not any(overlaps(box, o) for o in placed[:i]), box


def test_deleted_ink_does_not_block_placement(client):
    seed(client, [stroke("gone", 0, 0, w=100, h=100, isDeleted=True)])
    assert write(client).json()["payload"]["placement"] == {"x": 0, "y": 0}


def test_ops_rows_hold_document_created_at_and_result(client):
    op = write(client).json()
    measure(client, op["id"])
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM agent_ops WHERE id = ?", (op["id"],)).fetchone()
    finally:
        conn.close()
    assert row["document_id"] == "default" and row["created_at"]
    assert [e["id"] for e in json.loads(row["elements_json"])] == [own(op["id"])]


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
    gap = max(gap_for(op["payload"]["font_size"]), 1.05 * proximity_threshold([USER_A]))
    assert op["payload"]["placement"] == {"x": box["x"] + box["width"] + gap, "y": box["y"]}


def test_placement_avoids_the_corners_of_rotated_ink(client):
    import math

    from inkbridge.agent.placement import estimate_size

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
    box = _op_box(op, estimate_size("write_text", op["payload"]))
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


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("sequenceDiagram\n  Alice->>Bob: hi", "sequenceDiagram"),
        ("classDiagram\n  A <|-- B", "classDiagram"),
        ('pie\n  "a": 1', "pie"),
        ("A-->B", "A"),
    ],
)
def test_draw_diagram_refuses_anything_but_a_flowchart(client, source, kind):
    r = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": source}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "not_flowchart" and detail["diagram_type"] == kind
    assert "flowchart" in detail["msg"]
    assert client.get(OPS).json()["ops"] == []


def test_draw_diagram_accepts_graph_and_flowchart_headers(client):
    for source in ("graph LR\n  A-->B", "%%{init: {}}%%\nflowchart TD\n  A-->B"):
        r = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": source}})
        assert r.status_code == 201, r.json()


# --- font size from the handwriting (INK-066) ---------------------------------------------------


def _strokes(prefix, x, y, height, n=5, **extra):
    return [{**stroke(f"{prefix}{i}", x + i * 5, y, w=4, h=height), **extra} for i in range(n)]


def _font(client, **payload):
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", **payload}})
    assert r.status_code == 201, r.text
    return r.json()["payload"]["font_size"]


def test_font_size_follows_the_anchor_chunks_strokes(client):
    from inkbridge.agent.placement import MAX_FONT, MIN_FONT

    seed(client, _strokes("s", 0, 0, 20) + _strokes("t", 5000, 5000, 60))
    small = _font(client, anchor=_anchor_region([f"s{i}" for i in range(5)]))
    big = _font(client, anchor=_anchor_region([f"t{i}" for i in range(5)]))
    assert MIN_FONT <= small < big <= MAX_FONT


def test_empty_canvas_uses_the_default_font(client):
    from inkbridge.agent.placement import DEFAULT_FONT

    assert _font(client) == DEFAULT_FONT


def test_sparse_anchor_falls_back_to_latest_strokes_not_default(client):
    from inkbridge.agent.placement import DEFAULT_FONT

    shape = {"id": "box", "type": "rectangle", "x": 9000, "y": 9000, "width": 50, "height": 50}
    seed(client, _strokes("o", 0, 0, 10, n=2) + _strokes("t", 5000, 0, 200, n=60) + [shape])
    big = _font(client)
    assert big > DEFAULT_FONT
    assert _font(client, anchor=_anchor_region(["box"])) == big
    assert _font(client, anchor=_anchor_region(["o0", "o1"])) == big  # 2 strokes < MIN_SAMPLES


def test_font_size_at_10x_is_10x_of_1x(client):
    seed(client, _strokes("s", 0, 0, 20))
    one = _font(client)
    seed(client, _strokes("s", 0, 0, 200, version=2))  # same ids edited: a higher version wins
    ten = _font(client)
    assert abs(ten - 10 * one) <= 1 and ten > 64


def _gap(client, height, prefix, x):
    seed(client, _strokes(prefix, x, 0, height))
    rid = _anchor_region([f"{prefix}{i}" for i in range(5)])
    conn = db.connect()
    try:
        bbox = json.loads(
            conn.execute("SELECT bbox FROM regions WHERE id = ?", (rid,)).fetchone()[0]
        )
    finally:
        conn.close()
    op = client.post(
        OPS, json={"type": "write_text", "payload": {"text": "x", "anchor": rid}}
    ).json()
    return op["payload"]["placement"]["x"] - (bbox["x"] + bbox["width"])


def test_placement_gap_scales_with_ink(client):
    assert _gap(client, 20, "a", 0) == 40
    assert _gap(client, 200, "b", 90000) >= 200


def test_same_anchor_same_size_across_ops_and_after_accept(client):
    seed(client, _strokes("s", 0, 0, 40))
    rid = _anchor_region([f"s{i}" for i in range(5)])
    first = client.post(
        OPS, json={"type": "write_text", "payload": {"text": "a", "anchor": rid}}
    ).json()
    second = _font(client, anchor=rid)
    assert second == first["payload"]["font_size"]
    measure(client, first["id"])
    assert client.post(f"/ops/{first['id']}/accept", json={}).status_code == 200
    assert _font(client, anchor=rid) == second


def test_client_cannot_set_wrap_chars(client):  # payload models forbid extras; keep it that way
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "wrap_chars": 5}})
    assert r.status_code == 422


def test_agent_drafts_do_not_feed_back_into_scale(client):
    draft = {"customData": {"draft": True, "author": "agent"}}
    seed(client, _strokes("s", 0, 0, 20))
    before = _font(client)
    seed(client, _strokes("s", 0, 0, 20) + _strokes("d", 3000, 3000, 200, **draft))
    assert _font(client) == before


def test_size_hint_scales_and_unknown_hint_is_422(client):
    seed(client, _strokes("s", 0, 0, 20))
    assert _font(client, size="large") > _font(client, size="normal")
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "size": "huge"}})
    assert r.status_code == 422


def test_client_cannot_set_font_size(client):
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "font_size": 99}})
    assert r.status_code == 422


def test_idempotent_retry_with_computed_font_size_is_not_a_conflict(client):
    seed(client, _strokes("s", 0, 0, 20))
    body = {"type": "write_text", "payload": {"text": "x", "size": "large"}, "op_id": "op-fs"}
    r1, r2 = client.post(OPS, json=body), client.post(OPS, json=body)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json() == r2.json() and "font_size" in r1.json()["payload"]


# --- INK-045: resolving drafts (Accept / Reject) ------------------------------------------------


def test_twenty_ops_can_all_be_accepted(client):
    ids = []
    for i in range(20):
        op = write(client, f"t{i}").json()
        measure(client, op["id"])
        ids.append(op["id"])
    for op_id in ids:
        r = client.post(f"/ops/{op_id}/accept", json={})
        assert r.status_code == 200 and r.json()["op"]["status"] == "accepted"
    accepted = client.get(OPS, params={"status": "accepted"}).json()["ops"]
    assert {o["id"] for o in accepted} == set(ids)
    assert len(accepted) == 20


@pytest.mark.parametrize("verdict", ["accepted", "rejected"])
@pytest.mark.parametrize("delivered", [False, True])
def test_resolving_an_unapplied_op_is_409(client, verdict, delivered):
    op = write(client).json()
    if delivered:
        conn = db.connect()
        try:
            ops_db.mark_delivered(conn, op["id"])
        finally:
            conn.close()
    url = f"/ops/{op['id']}/{'accept' if verdict == 'accepted' else 'reject'}"
    assert client.post(url, json={}).status_code == 409
    assert client.get(f"/ops/{op['id']}").json()["status"] == (
        "delivered" if delivered else "pending"
    )


def test_resolving_never_touches_the_stored_scene(client):
    seed(client)
    op = write(client).json()
    measure(client, op["id"])
    before = client.get(SCENE).json()
    r = client.post(f"/ops/{op['id']}/reject")
    assert r.status_code == 200
    after = client.get(SCENE).json()
    assert after["version"] == before["version"]
    assert after["elements"] == before["elements"]


def _link(rid, **cols):
    conn = db.connect()
    try:
        sets = ", ".join(f"{k} = ?" for k in cols)
        conn.execute(f"UPDATE regions SET {sets} WHERE id = ?", (*cols.values(), rid))
        conn.commit()
    finally:
        conn.close()


def test_orphaned_anchor_resolves_to_successor(client):
    seed(client)
    a, b = _anchor_region(["user-a"]), _anchor_region(["user-b"])
    _link(a, status="orphaned", successor_of=b)
    op = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "anchor": a}})
    assert op.status_code == 201
    box = bbox_of([USER_B])
    assert op.json()["payload"]["anchor_resolved"] == b
    assert op.json()["payload"]["placement"]["x"] == box["x"] + box["width"] + _clear_gap(
        op.json(), [USER_A, USER_B]
    )


@pytest.mark.fts_unchecked
def test_successor_cycle_does_not_hang(client):
    seed(client)
    a, b = _anchor_region(["user-a"]), _anchor_region(["user-b"])
    _link(a, status="orphaned", successor_of=b)
    _link(b, status="orphaned", successor_of=a)
    op = client.post(OPS, json={"type": "write_text", "payload": {"text": "x", "anchor": a}})
    assert op.status_code == 422


def _op_body(kind, anchor):
    if kind == "write_text":
        return {"type": kind, "payload": {"text": "x", "anchor": anchor}}
    return {"type": kind, "payload": {"mermaid": "flowchart TD\nA-->B", "anchor": anchor}}


@pytest.mark.parametrize("kind", ["write_text", "draw_diagram"])
def test_chain_of_two_orphans_reaches_live(client, kind):
    seed(client)
    a, c = _anchor_region(["user-a"]), _anchor_region(["user-b"])
    # a -> mid (orphan) -> c (active): mid is a fresh row copied from a
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO regions (id, document_id, element_ids_json, bbox, status, successor_of,"
            " created_by) SELECT 'mid', document_id, element_ids_json, bbox, 'orphaned', ?,"
            " created_by FROM regions WHERE id = ?",
            (c, a),
        )
        conn.commit()
    finally:
        conn.close()
    _link(a, status="orphaned", successor_of="mid")
    r = client.post(OPS, json=_op_body(kind, a))
    assert r.status_code == 201, r.text
    assert r.json()["payload"]["anchor_resolved"] == c
    box = bbox_of([USER_B])
    assert r.json()["payload"]["placement"]["x"] == box["x"] + box["width"] + _clear_gap(
        r.json(), [USER_A, USER_B]
    )


@pytest.mark.parametrize("kind", ["write_text", "draw_diagram"])
@pytest.mark.fts_unchecked
@pytest.mark.parametrize("shape", ["no_successor", "cycle"])
def test_dead_anchor_is_422_gone(client, kind, shape):
    seed(client)
    a, b = _anchor_region(["user-a"]), _anchor_region(["user-b"])
    if shape == "no_successor":
        _link(a, status="orphaned", successor_of=None)
    else:
        _link(a, status="orphaned", successor_of=b)
        _link(b, status="orphaned", successor_of=a)
    r = client.post(OPS, json=_op_body(kind, a))
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "anchor_gone" and "read_canvas" in detail["msg"]
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM agent_ops").fetchone()[0] == 0
    finally:
        conn.close()


def test_client_sent_anchor_resolved_is_ignored(client):
    seed(client)
    op = client.post(
        OPS, json={"type": "write_text", "payload": {"text": "x", "anchor_resolved": "forged"}}
    )
    # the payload schema rejects unknown keys; _create_op strips it as well
    assert op.status_code == 422 or "anchor_resolved" not in op.json()["payload"]


def _write_at(client, text, anchor):
    payload = {"text": text, **({"anchor": anchor} if anchor else {})}
    r = client.post(OPS, json={"type": "write_text", "payload": payload})
    assert r.status_code == 201, r.text
    return r.json()


def _clear_gap(op, scene):
    return max(gap_for(op["payload"]["font_size"]), 1.05 * proximity_threshold(scene))


def _page(scale):
    return [stroke(f"u{i}", 0, 1000 * scale * i, w=30 * scale, h=40 * scale) for i in range(3)]


def _dist(a, b):
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


@pytest.mark.parametrize("scale", [1, 10])
def test_draft_is_farther_than_chunker_threshold_from_every_chunk(client, scale):
    page = _page(scale)
    seed(client, page)
    threshold = proximity_threshold(page)
    assert threshold == 1.5 * 40 * scale
    op = _write_at(client, "x", _anchor_region(["u0"]))
    box = _op_box(op, estimate_size("write_text", op["payload"]))
    for e in page:
        b = bbox_of([e])
        dx = max(b["x"] - (box["x"] + box["width"]), box["x"] - (b["x"] + b["width"]), 0)
        dy = max(b["y"] - (box["y"] + box["height"]), box["y"] - (b["y"] + b["height"]), 0)
        assert (dx**2 + dy**2) ** 0.5 > threshold


@pytest.mark.parametrize("anchored", [False, True])
@pytest.mark.parametrize("scale", [1, 10])
def test_five_ops_form_a_tight_column(client, scale, anchored):
    page = _page(scale)
    seed(client, page)
    anchor = _anchor_region(["u0"]) if anchored else None
    spots = []
    for i in range(5):
        op = _write_at(client, f"note {i}", anchor)
        spots.append(op["payload"]["placement"])
        est_h = estimate_size("write_text", op["payload"])[1]
        gap = max(gap_for(op["payload"]["font_size"]), 1.05 * proximity_threshold(page))
    bound = 5 * (est_h + 2 * gap)
    assert max(_dist(a, b) for a in spots for b in spots) <= bound


def test_placed_op_reserves_real_box_not_estimate(client):
    seed(client, [stroke("u0", 0, 0), stroke("u1", 0, 20000), stroke("u2", 0, 40000)])
    op = write(client, text="a\n" * 20).json()
    est = estimate_size("write_text", op["payload"])
    p = op["payload"]["placement"]
    placed = measure(client, op["id"], width=10, height=10)
    nxt = write(client, text="b").json()["payload"]["placement"]
    assert nxt["y"] < p["y"] + est[1]  # the estimate would have kept it below
    assert nxt["y"] >= placed["box"]["y"] + 10


# --- INK-088: pending and delivered ops expire after 24 h -------------------------------------


def _backdate(op_id, hours):
    """Age an op's created_at as if it were enqueued that many hours ago."""
    from datetime import UTC, datetime, timedelta

    ts = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    conn = db.connect()
    try:
        conn.execute("UPDATE agent_ops SET created_at = ? WHERE id = ?", (ts, op_id))
        conn.commit()
    finally:
        conn.close()


def test_op_older_than_ttl_expires_and_leaves_the_cap(client, monkeypatch):
    monkeypatch.setattr(ops_db, "MAX_OPEN_OPS", 1)  # the stale op would block the next if counted
    seed(client)
    old = write(client).json()["id"]
    _backdate(old, 25)
    assert write(client).status_code == 201
    assert client.get(f"/ops/{old}").json()["status"] == "expired"


def test_fresh_op_is_not_expired(client):
    seed(client)
    op = write(client).json()["id"]
    _backdate(op, 23)
    assert write(client).status_code == 201
    assert client.get(f"/ops/{op}").json()["status"] == "pending"


def test_placed_op_is_never_expired(client):
    seed(client)
    op = write(client).json()["id"]
    measure(client, op)
    _backdate(op, 48)
    write(client, "later")  # runs the sweep
    assert client.get(f"/ops/{op}").json()["status"] == "placed"


def test_delivered_op_expires_too(client):
    seed(client)
    op = write(client).json()["id"]
    conn = db.connect()
    try:
        ops_db.mark_delivered(conn, op)
    finally:
        conn.close()
    _backdate(op, 25)
    assert client.get(OPS, params={"status": "pending,delivered"}).json()["ops"] == []
    assert client.get(f"/ops/{op}").json()["status"] == "expired"


def test_expired_op_is_not_listed_as_pending(client):
    seed(client)
    op = write(client).json()["id"]
    _backdate(op, 25)
    assert client.get(OPS, params={"status": "pending"}).json()["ops"] == []


def test_stale_op_without_created_at_is_never_expired(client):
    # Rows from before migration 0004 have no created_at; they must not be swept.
    seed(client)
    op = write(client).json()["id"]
    conn = db.connect()
    try:
        conn.execute("UPDATE agent_ops SET created_at = NULL WHERE id = ?", (op,))
        conn.commit()
        ops_db.list_ops(conn, "default", ["pending"])  # the sweep runs here
        assert ops_db.get_op(conn, op)["status"] == "pending"
    finally:
        conn.close()


def test_too_many_open_is_informative(client, monkeypatch):
    monkeypatch.setattr(ops_db, "MAX_OPEN_OPS", 1)
    seed(client)
    first = write(client).json()
    r = write(client, "second")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "too_many_open_ops"
    assert detail["open"] == 1
    assert detail["since"] == first["created_at"]
    assert "since" in detail["msg"] and first["created_at"] in detail["msg"]
    assert "24 h" in detail["msg"]
