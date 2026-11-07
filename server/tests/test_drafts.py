"""Drafts live in the op row until Accept (INK-114, decision 0086)."""

import json
from contextlib import closing

import pytest

from inkbridge import db
from inkbridge.db import drafts
from inkbridge.db import ops as ops_db
from tests.test_ops_api import SCENE, seed, write


def els(op_id, n=1, **extra):
    return [
        {
            "id": f"{op_id}:{i}",
            "type": "text",
            "x": 10 * i,
            "y": 5 * i,
            "width": 120,
            "height": 30,
            "text": "hi",
            "fontSize": 20,
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
            **extra,
        }
        for i in range(1, n + 1)
    ]


def measure(client, op, n=1, width=120, height=30):
    """Measure an op the way the browser would, through the db layer."""
    with closing(db.connect()) as conn:
        return drafts.measure_op(conn, op["id"], els(op["id"], n), width, height)


def post(client, text="hello"):
    r = write(client, text)
    assert r.status_code == 201
    return r.json()


def scene_rows(op_id):
    with closing(db.connect()) as conn:
        return [
            json.loads(r["json"])
            for r in conn.execute(
                "SELECT json FROM scene_elements WHERE id LIKE ?", (f"{op_id}:%",)
            )
        ]


def head():
    with closing(db.connect()) as conn:
        return db.scene_version(conn, "default")


# --- measure ----------------------------------------------------------------------------------


def test_measure_places_with_true_size(client):
    seed(client)
    op = post(client)
    got = measure(client, op, n=2, width=300, height=80)
    assert got["status"] == "placed"
    assert all(e["id"].startswith(f"{op['id']}:") for e in got["elements"])
    want = {"author": "agent", "op_id": op["id"], "draft": True}
    assert all(e["customData"] == want for e in got["elements"])
    assert (got["box"]["width"], got["box"]["height"]) == (300, 80)
    xs = min(e["x"] for e in got["elements"])
    ys = min(e["y"] for e in got["elements"])
    assert (xs, ys) == (got["box"]["x"], got["box"]["y"])


def test_measure_refuses_foreign_ids(client):
    seed(client)
    op = post(client)
    with closing(db.connect()) as conn:
        for bad in ("other:1", "user-a"):
            e = els(op["id"])
            e[0]["id"] = bad
            with pytest.raises(ops_db.ExistingElementIds):
                drafts.measure_op(conn, op["id"], e, 100, 30)
        assert ops_db.get_op(conn, op["id"])["status"] in ("pending", "delivered")


def test_measure_twice_is_noop(client):
    op = post(client)
    first = measure(client, op)
    again = measure(client, op, n=3)
    assert again == first


def test_two_placed_drafts_do_not_overlap(client):
    seed(client)
    a, b = post(client, "a"), post(client, "b")
    ba, bb = measure(client, a)["box"], measure(client, b)["box"]
    assert not (
        ba["x"] < bb["x"] + bb["width"]
        and bb["x"] < ba["x"] + ba["width"]
        and ba["y"] < bb["y"] + bb["height"]
        and bb["y"] < ba["y"] + ba["height"]
    )


def test_applied_status_gone(client):
    assert "applied" not in ops_db.STATUSES
    op = post(client)
    assert client.patch(f"/ops/{op['id']}", json={"status": "applied"}).status_code == 422
    assert client.patch(f"/ops/{op['id']}", json={"status": "placed"}).status_code == 422


# --- accept / reject / unaccept -----------------------------------------------------------------


def accept(client, op_id, **body):
    return client.post(f"/ops/{op_id}/accept", json=body)


def test_accept_moves_draft_into_scene(client):
    seed(client)
    op = post(client)
    measure(client, op)
    before = head()
    r = accept(client, op["id"])
    assert r.status_code == 200
    body = r.json()
    assert body["seq"] == head() > before
    rows = scene_rows(op["id"])
    assert [e["id"] for e in rows] == [f"{op['id']}:1"]
    e = rows[0]
    assert "draft" not in e["customData"] and e["customData"]["author"] == "agent"
    assert e["strokeStyle"] == "solid" and e["opacity"] == 100 and e["version"] == 2
    assert body["op"]["status"] == "accepted" and body["op"]["resolved_at"]
    chunks = client.get("/documents/default/regions?chunks=true").json()
    got = [c for c in chunks if sorted(c["element_ids"]) == [f"{op['id']}:1"]]
    assert len(got) == 1


def test_double_accept_same_seq(client):
    op = post(client)
    measure(client, op)
    first = accept(client, op["id"]).json()
    h = head()
    second = accept(client, op["id"]).json()
    assert second["seq"] == first["seq"] and head() == h
    assert len(scene_rows(op["id"])) == 1


def test_accept_offset_applies_and_is_bounded(client):
    op = post(client)
    placed = measure(client, op, n=2)["elements"]
    assert accept(client, op["id"], dx=20001).status_code == 422
    assert client.get(f"/ops/{op['id']}").json()["status"] == "placed"
    assert accept(client, op["id"], dx=50, dy=-20).status_code == 200
    got = {e["id"]: e for e in scene_rows(op["id"])}
    for p in placed:
        assert (got[p["id"]]["x"], got[p["id"]]["y"]) == (p["x"] + 50, p["y"] - 20)


def test_colliding_accept_is_refused(client):
    op = post(client)
    measure(client, op)
    with closing(db.connect()) as conn:
        conn.execute(
            "INSERT INTO scene_elements (document_id, id, pos, seq, version, nonce, is_deleted, json,"
            " updated_at) VALUES ('default', ?, 99, 1, 1, 1, 0, '{\"id\":\"x\",\"type\":\"text\"}', 'now')",
            (f"{op['id']}:1",),
        )
        conn.commit()
    h = head()
    r = accept(client, op["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "id_collision"
    assert r.json()["detail"]["ids"] == [f"{op['id']}:1"]
    assert client.get(f"/ops/{op['id']}").json()["status"] == "placed" and head() == h


def test_accept_refuses_foreign_prefix(client):
    op = post(client)
    measure(client, op)
    with closing(db.connect()) as conn:
        e = els(op["id"])
        e[0]["id"] = "stranger:1"
        conn.execute("UPDATE agent_ops SET elements_json=? WHERE id=?", (json.dumps(e), op["id"]))
        conn.commit()
    r = accept(client, op["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bad_prefix"


def test_accept_needs_placed(client):
    pending = post(client)
    r = accept(client, pending["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_transition"
    rej = post(client, "b")
    measure(client, rej)
    assert client.post(f"/ops/{rej['id']}/reject").status_code == 200
    assert accept(client, rej["id"]).status_code == 409


def test_reject_idempotent(client):
    op = post(client)
    measure(client, op)
    h = head()
    for _ in range(2):
        r = client.post(f"/ops/{op['id']}/reject")
        assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert scene_rows(op["id"]) == [] and head() == h
    acc = post(client, "c")
    measure(client, acc)
    accept(client, acc["id"])
    assert client.post(f"/ops/{acc['id']}/reject").status_code == 409


def test_unaccept_removes_only_unchanged(client):
    seed(client)
    op = post(client)
    with closing(db.connect()) as conn:
        drafts.measure_op(conn, op["id"], els(op["id"], 3), 200, 60)
    accept(client, op["id"])
    mine = {e["id"]: e for e in scene_rows(op["id"])}
    edited = {**mine[f"{op['id']}:2"], "version": mine[f"{op['id']}:2"]["version"] + 1, "x": 999}
    assert client.post("/documents/default/elements", json={"device": "d1", "batch": 1, "elements": [edited]}).status_code == 200
    r = client.post(f"/ops/{op['id']}/unaccept")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body["removed"]) == [f"{op['id']}:1", f"{op['id']}:3"]
    assert body["kept"] == [f"{op['id']}:2"]
    now = {e["id"]: e for e in scene_rows(op["id"])}
    assert now[f"{op['id']}:1"]["isDeleted"] and now[f"{op['id']}:1"]["version"] == 3
    assert not now[f"{op['id']}:2"].get("isDeleted") and now[f"{op['id']}:2"]["x"] == 999
    assert body["op"]["status"] == "placed" and len(body["op"]["elements"]) == 3
    live = client.get(SCENE).json()["elements"]
    assert {"user-a", "user-b"} <= {e["id"] for e in live if not e.get("isDeleted")}


def test_unaccept_window(client, monkeypatch):
    op = post(client)
    measure(client, op)
    accept(client, op["id"])
    monkeypatch.setattr(drafts, "UNACCEPT_WINDOW_S", -1)
    r = client.post(f"/ops/{op['id']}/unaccept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "window_closed"


def test_unaccept_on_placed_is_409(client):
    op = post(client)
    measure(client, op)
    assert client.post(f"/ops/{op['id']}/unaccept").status_code == 409


def test_get_drafts(client):
    a, b = post(client, "a"), post(client, "b")
    post(client, "c")
    measure(client, b)
    measure(client, a)
    r = client.get("/documents/default/drafts")
    assert [d["id"] for d in r.json()["drafts"]] == [a["id"], b["id"]]
    assert r.json()["drafts"][0]["elements"] and r.json()["drafts"][0]["box"]
    assert client.get("/documents/nope/drafts").status_code == 404


def test_accept_publishes_scene_delta(client):
    from tests.test_ws import WS, recv

    op = post(client)
    measure(client, op)
    with client.websocket_connect(WS) as ws:
        while recv(ws)["type"] != "op.placed":
            pass
        accept(client, op["id"])
        got = [recv(ws) for _ in range(3)]
    delta = next(m for m in got if m["type"] == "scene.delta")
    assert [e["id"] for e in delta["elements"]] == [f"{op['id']}:1"]
    assert delta["origin"] == "" and "draft" not in delta["elements"][0]["customData"]
