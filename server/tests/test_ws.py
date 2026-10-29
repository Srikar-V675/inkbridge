"""WebSocket push channel (INK-042): op.pending push and replay, acks, op.updated, chunks.updated."""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import pytest
from starlette.websockets import WebSocketDisconnect

from inkbridge import db
from inkbridge.db import ops as ops_db

OPS = "/documents/default/ops"
WS = "/ws?document=default"
_pool = ThreadPoolExecutor(max_workers=4)


def recv(ws, timeout=2.0):
    """receive_json with a deadline, so a missing push fails instead of hanging."""
    try:
        return _pool.submit(ws.receive_json).result(timeout=timeout)
    except FutureTimeout:
        pytest.fail(f"no message within {timeout}s")


def write(client, text="hello"):
    r = client.post(OPS, json={"type": "write_text", "payload": {"text": text}})
    assert r.status_code == 201
    return r.json()


def status(client, op_id):
    return client.get(f"/ops/{op_id}").json()["status"]


def wait_status(client, op_id, want, timeout=2.0):
    """The server marks an op delivered just after the send, so a reader can briefly see pending."""
    deadline = time.monotonic() + timeout
    while (got := status(client, op_id)) != want and time.monotonic() < deadline:
        time.sleep(0.01)
    return got


def test_op_posted_while_connected_is_pushed_within_a_second(client):
    with client.websocket_connect(WS) as ws:
        t0 = time.monotonic()
        op = write(client)
        msg = recv(ws, timeout=1.0)
        assert time.monotonic() - t0 < 1.0
    assert msg == {
        "type": "op.pending",
        "op_id": op["id"],
        "op_type": "write_text",
        "payload": op["payload"],
    }
    assert msg["payload"]["id_prefix"] == f"{op['id']}:"
    assert wait_status(client, op["id"], "delivered") == "delivered"


def test_ops_waiting_before_connect_are_replayed_and_marked_delivered(client):
    a, b = write(client, "a"), write(client, "b")
    with client.websocket_connect(WS) as ws:
        got = [recv(ws)["op_id"], recv(ws)["op_id"]]
    assert got == [a["id"], b["id"]]
    assert status(client, a["id"]) == "delivered"


def test_delivered_but_unacked_ops_are_replayed_on_reconnect(client):
    op = write(client)
    with client.websocket_connect(WS) as ws:
        assert recv(ws)["op_id"] == op["id"]
    with client.websocket_connect(WS) as ws:  # the browser reloaded before acking
        assert recv(ws)["op_id"] == op["id"]


def test_ack_over_the_socket_applies_and_stops_the_replay(client):
    op = write(client)
    ids = [f"{op['id']}:1"]
    with client.websocket_connect(WS) as ws:
        recv(ws)
        ws.send_json({"type": "op.applied", "op_id": op["id"], "element_ids": ids})
        assert recv(ws) == {
            "type": "op.updated",
            "op_id": op["id"],
            "status": "applied",
            "error": None,
        }
    assert client.get(f"/ops/{op['id']}").json()["result"] == {"element_ids": ids}
    later = write(client, "later")
    with client.websocket_connect(WS) as ws:
        assert recv(ws)["op_id"] == later["id"]  # the applied op is not sent again


def test_ack_naming_user_ink_is_refused_over_the_socket(client):
    client.put("/documents/default/scene", json={"base_version": 0, "elements": [{"id": "ink"}]})
    op = write(client)
    with client.websocket_connect(WS) as ws:
        recv(ws)
        ws.send_json({"type": "op.applied", "op_id": op["id"], "element_ids": ["ink"]})
        msg = recv(ws)
    assert msg["type"] == "op.error" and msg["code"] == "existing_element_id"
    assert msg["detail"] == ["ink"]
    assert status(client, op["id"]) == "delivered"


def test_failed_over_the_socket_records_the_error(client):
    op = client.post(OPS, json={"type": "draw_diagram", "payload": {"mermaid": "x"}}).json()
    with client.websocket_connect(WS) as ws:
        recv(ws)
        ws.send_json({"type": "op.failed", "op_id": op["id"], "error": "parse error"})
        assert recv(ws)["status"] == "failed"
    assert client.get(f"/ops/{op['id']}").json()["error"] == "parse error"


def test_ack_for_an_op_of_another_document_is_refused(client):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO documents (id, title, updated_at) VALUES ('other', 'O', 'now')")
        conn.execute(
            "INSERT INTO scenes (document_id, version, elements_json, updated_at)"
            " VALUES ('other', 0, '[]', 'now')"
        )
        conn.commit()
    finally:
        conn.close()
    other = client.post(
        "/documents/other/ops", json={"type": "write_text", "payload": {"text": "x"}}
    ).json()
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "op.applied", "op_id": other["id"], "element_ids": ["other-id:1"]})
        assert recv(ws)["code"] == "not_found"
    assert status(client, other["id"]) == "pending"


def test_bad_messages_get_an_error_and_keep_the_socket(client):
    with client.websocket_connect(WS) as ws:
        ws.send_text("not json")
        assert recv(ws)["type"] == "error"
        ws.send_json({"type": "op.nope", "op_id": "x"})
        assert recv(ws)["type"] in ("error", "op.error")
        op = write(client)
        assert recv(ws)["op_id"] == op["id"]


def test_unknown_document_is_closed(client):
    with (
        pytest.raises(WebSocketDisconnect) as e,
        client.websocket_connect("/ws?document=nope") as ws,
    ):
        ws.receive_json()
    assert e.value.code == 4404


def test_patch_is_broadcast_as_op_updated(client):
    op = write(client)
    with client.websocket_connect(WS) as ws:
        recv(ws)
        client.patch(f"/ops/{op['id']}", json={"status": "expired"})
        assert recv(ws) == {
            "type": "op.updated",
            "op_id": op["id"],
            "status": "expired",
            "error": None,
        }


def test_scene_save_pushes_chunks_updated(client):
    with client.websocket_connect(WS) as ws:
        client.put("/documents/default/scene", json={"base_version": 0, "elements": []})
        assert recv(ws) == {"type": "chunks.updated", "version": 1, "stale_crops": []}


def test_mark_delivered_reports_whether_it_moved_the_op(client):
    op = write(client)
    conn = db.connect()
    try:
        assert ops_db.mark_delivered(conn, op["id"]) is True
        assert ops_db.mark_delivered(conn, op["id"]) is False
        ops_db.update_status(conn, op["id"], "applied", [f"{op['id']}:1"])
        assert ops_db.mark_delivered(conn, op["id"]) is False
        assert ops_db.get_op(conn, op["id"])["status"] == "applied"
    finally:
        conn.close()


def test_an_op_resolved_before_its_push_is_not_sent(client):
    from inkbridge.api.ws import hub

    # Resolve the op before connecting: the connect-time replay runs concurrently with the test
    # thread, so an op still pending while it lists ops would be replayed (correctly) and sent.
    conn = db.connect()
    try:
        stale, _ = ops_db.create_op(conn, "default", "write_text", {"text": "late"})
        ops_db.update_status(conn, stale["id"], "expired")
    finally:
        conn.close()
    with client.websocket_connect(WS) as ws:
        # The push queued at enqueue runs after the PATCH; wait for it so the order is fixed.
        hub.publish("default", op=stale).result(timeout=2)
        fresh = write(client, "fresh")
        assert recv(ws)["op_id"] == fresh["id"]
    assert status(client, stale["id"]) == "expired"


def test_a_binary_frame_gets_an_error_and_keeps_the_socket(client):
    with client.websocket_connect(WS) as ws:
        ws.send_bytes(b"\x00\x01")
        assert recv(ws)["type"] == "error"
        op = write(client)
        assert recv(ws)["op_id"] == op["id"]


def test_an_ack_over_the_http_limits_is_refused(client):
    op = write(client)
    prefix = op["payload"]["id_prefix"]
    with client.websocket_connect(WS) as ws:
        recv(ws)
        for ids in ([prefix + "x" * 300], [f"{prefix}{i}" for i in range(10_001)]):
            ws.send_json({"type": "op.applied", "op_id": op["id"], "element_ids": ids})
            assert recv(ws)["code"] == "bad_ack"
    assert status(client, op["id"]) == "delivered"


def test_a_page_from_another_origin_cannot_connect(client):
    with (
        pytest.raises(WebSocketDisconnect) as e,
        client.websocket_connect(WS, headers={"origin": "https://evil.example"}) as ws,
    ):
        write(client)  # an accepted socket would get this op pushed
        recv(ws)
    assert e.value.code == 4403


def test_a_page_from_this_host_can_connect(client):
    op = write(client)
    with client.websocket_connect(WS, headers={"origin": "http://testserver"}) as ws:
        assert recv(ws)["op_id"] == op["id"]
