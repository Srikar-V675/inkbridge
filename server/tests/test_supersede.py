"""INK-199: a replaced chunk supersedes its open offers and drafts (decision 0114)."""

import json

from inkbridge import db
from inkbridge.agent import detectors
from inkbridge.db import offers as offers_db
from inkbridge.db import supersede
from tests.test_chunk_persistence import Canvas, row
from tests.test_detectors import age
from tests.test_search import recognise


def two(client, a="Why?", b="Why not?"):
    """Chunk A (to be replaced) and chunk B far away; both read and settled."""
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    ca, cb = canvas.chunk_of("a0"), canvas.chunk_of("b0")
    recognise(ca, a)
    recognise(cb, b)
    age()
    return ca, cb


def sql(q, *args):
    conn = db.connect()
    try:
        conn.execute(q, args)
        conn.commit()
    finally:
        conn.close()


def orphan(a, successor=None):
    sql("UPDATE regions SET status='orphaned', successor_of=? WHERE id=?", successor, a["id"])


def offer_on(chunk, kind="question"):
    conn = db.connect()
    try:
        o, _ = offers_db.create_offer(
            conn, "default", kind=kind, anchor_chunk=chunk["id"], reason="r",
            payload={"key": "k"}, score=0.9,
        )  # fmt: skip
        return o
    finally:
        conn.close()


def run_supersede():
    conn = db.connect()
    try:
        return supersede.run(conn, "default")
    finally:
        conn.close()


def op_on(chunk, status, op_id="op1"):
    sql(
        "INSERT INTO agent_ops (id, document_id, type, payload_json, status, created_at,"
        " elements_json, box_json) VALUES (?,?,?,?,?,?,?,?)",
        op_id, "default", "write_text", json.dumps({"anchor": chunk["id"]}), status,
        "2026-11-10T00:00:00+00:00", "[]", json.dumps({"x": 0, "y": 0, "width": 10, "height": 10}),
    )  # fmt: skip


def op_status(op_id="op1"):
    conn = db.connect()
    try:
        return conn.execute("SELECT status, error FROM agent_ops WHERE id=?", (op_id,)).fetchone()
    finally:
        conn.close()


def test_open_offer_on_replaced_chunk_expires(client):
    a, b = two(client)
    o = offer_on(a)
    orphan(a, successor=b["id"])
    offers, _ = run_supersede()
    assert [x["id"] for x in offers] == [o["id"]] and offers[0]["status"] == "expired"


def test_open_offer_on_replaced_chunk_without_successor_uses_overlap(client):
    a, b = two(client)
    sql(
        "UPDATE regions SET bbox=(SELECT bbox FROM regions WHERE id=?) WHERE id=?", a["id"], b["id"]
    )
    o = offer_on(a)
    orphan(a)  # no successor_of: the chunker re-clustered the line
    offers, _ = run_supersede()
    assert [x["id"] for x in offers] == [o["id"]]


def test_orphan_with_no_cover_keeps_offer(client):
    a, _b = two(client)
    o = offer_on(a)
    orphan(a)  # ink deleted: nothing covers it
    offers, _ = run_supersede()
    assert offers == []
    conn = db.connect()
    assert offers_db.get_offer(conn, o["id"])["status"] == "open"
    conn.close()


def test_placed_draft_is_rejected_superseded(client):
    a, b = two(client)
    op_on(a, "placed")
    orphan(a, successor=b["id"])
    _, ops = run_supersede()
    assert [o["id"] for o in ops] == ["op1"]
    assert tuple(op_status()) == ("rejected", "superseded")


def test_pending_op_expires_superseded(client):
    a, b = two(client)
    op_on(a, "pending")
    orphan(a, successor=b["id"])
    run_supersede()
    assert tuple(op_status()) == ("expired", "superseded")


def test_accepted_op_untouched(client):
    a, b = two(client)
    op_on(a, "accepted")
    orphan(a, successor=b["id"])
    _, ops = run_supersede()
    assert ops == [] and op_status()["status"] == "accepted"


def test_no_second_offer_while_answer_pending(client):
    a, b = two(client, b="Why not?")
    o = offer_on(a)
    conn = db.connect()
    offers_db.tap_offer(conn, o["id"])
    task_id = offers_db.get_offer(conn, o["id"])["task_id"]
    conn.close()
    orphan(a, successor=b["id"])
    conn = db.connect()
    detectors.run(conn, "default")
    assert [x for x in offers_db.list_offers(conn, "default") if x["anchor_chunk"] == b["id"]] == []
    conn.execute("UPDATE agent_tasks SET status='done' WHERE id=?", (task_id,))
    conn.commit()
    detectors.run(conn, "default")
    assert (
        len([x for x in offers_db.list_offers(conn, "default") if x["anchor_chunk"] == b["id"]])
        == 1
    )
    conn.close()


def test_scan_now_publishes_op_updated(client, monkeypatch):
    from inkbridge.agent import attention as attention_mod
    from inkbridge.api import offers as offers_api
    from tests.test_offers_api import WS, Clock, open_gate

    clock = Clock()
    monkeypatch.setattr(attention_mod.attention, "clock", clock)
    monkeypatch.setattr(offers_api, "_ARM_TIMERS", False)
    a, b = two(client)
    op_on(a, "placed")
    orphan(a, successor=b["id"])
    with client.websocket_connect(WS) as ws:
        open_gate(ws, clock)
        offers_api.scan_now("default")
        seen = []
        for _ in range(6):
            msg = ws.receive_json()
            seen.append(msg)
            if msg["type"] == "op.updated":
                break
    op = next(m for m in seen if m["type"] == "op.updated")
    assert op["status"] == "rejected" and op["error"] == "superseded"
