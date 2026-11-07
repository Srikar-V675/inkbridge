"""INK-130: offers API, the attention gate over the WebSocket, budget, mute and Focus."""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import pytest

from inkbridge.agent import attention as attention_mod
from inkbridge.api import offers as offers_api
from tests.test_chunk_persistence import Canvas, row

WS = "/ws?document=default"
VIEW = {"x": 0, "y": 0, "width": 100, "height": 100, "zoom": 1}
_pool = ThreadPoolExecutor(max_workers=4)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_QUIET_S", "8")
    c = Clock()
    monkeypatch.setattr(attention_mod.attention, "clock", c)
    monkeypatch.setattr(offers_api, "_ARM_TIMERS", False)  # no real timers in tests
    offers_api.pushed.clear()
    offers_api._seen_session.clear()
    yield c
    for t in offers_api._timers.values():
        t.cancel()
    offers_api._timers.clear()


@pytest.fixture
def chunk(client, clock):
    return Canvas(client, row("a", 3)).chunks()[0]["id"]


def recv(ws, timeout=2.0):
    try:
        return _pool.submit(ws.receive_json).result(timeout=timeout)
    except FutureTimeout:
        pytest.fail(f"no message within {timeout}s")


def silent(ws, timeout=0.3):
    """True if nothing arrives. The pending receive is left running, so only the last call per socket."""
    try:
        _pool.submit(ws.receive_json).result(timeout=timeout)
    except FutureTimeout:
        return True
    return False


def post(client, chunk, score=0.5, kind="related", expect=201, **kw):
    body = {"kind": kind, "anchor_chunk": chunk, "reason": "why", "score": score, **kw}
    r = client.post("/documents/default/offers", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def attend(ws, pen):
    ws.send_json({"type": "attention", "pen": pen, "view": VIEW})
    time.sleep(0.15)  # the server reads the frame on another thread; the fake clock must not move first


def test_no_push_while_pen_down(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        attend(ws, True)
        offer = post(client, chunk)
        clock.t = 100
        attend(ws, False)  # the pen-up is a stroke end, so the quiet window starts now
        clock.t = 108
        attend(ws, False)
        msg = recv(ws)
    assert msg["type"] == "offer.created" and msg["offer"]["id"] == offer["id"]


def test_no_push_inside_quiet_window(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        attend(ws, False)
        clock.t = 7
        post(client, chunk)
        clock.t = 8
        attend(ws, False)  # 8 s after the last message: the window is over
        assert recv(ws)["type"] == "offer.created"


def test_waits_without_browser(client, chunk, clock):
    offer = post(client, chunk)
    assert [o["id"] for o in client.get("/documents/default/offers").json()["offers"]] == [
        offer["id"]
    ]
    with client.websocket_connect(WS) as ws:
        attend(ws, False)
        clock.t = 9
        attend(ws, False)
        assert recv(ws)["offer"]["id"] == offer["id"]


def open_gate(ws, clock):
    attend(ws, False)
    clock.t += 9
    attend(ws, False)


def test_fourth_offer_replaces_weakest_api(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        open_gate(ws, clock)
        ids = [post(client, chunk, s)["id"] for s in (0.2, 0.4, 0.6)]
        assert [recv(ws)["offer"]["id"] for _ in ids] == ids
        new = post(client, chunk, 0.9)
        upd, created = recv(ws), recv(ws)
        assert upd["type"] == "offer.updated" and upd["offer"]["id"] == ids[0]
        assert upd["offer"]["status"] == "expired"
        assert created["type"] == "offer.created" and created["offer"]["id"] == new["id"]
    live = client.get("/documents/default/offers", params={"status": "open"}).json()["offers"]
    assert sorted(o["score"] for o in live) == [0.4, 0.6, 0.9]
    r = client.post(
        "/documents/default/offers",
        json={"kind": "related", "anchor_chunk": chunk, "reason": "x", "score": 0.1},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "budget_full"


def test_mute_after_two_dismissals_api(client, chunk, clock):
    for _ in range(2):
        a = post(client, chunk)
        assert client.post(f"/offers/{a['id']}/dismiss").status_code == 200
    r = client.post(
        "/documents/default/offers",
        json={"kind": "related", "anchor_chunk": chunk, "reason": "x", "score": 0.5},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "kind_muted"
    post(client, chunk, kind="other")
    with client.websocket_connect(WS):
        pass
    post(client, chunk)  # a new session: the count restarts


def test_focus_holds_and_releases(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        open_gate(ws, clock)
        assert client.put("/documents/default/focus", json={"on": True}).json() == {"on": True}
        offer = post(client, chunk)
        assert client.get("/documents/default/offers").json() == {"offers": []}
        q = client.post("/documents/default/questions", json={"text": "hi"})
        assert q.status_code == 201
        assert recv(ws)["type"] == "question.update"  # asks ignore Focus, offers stay held
        client.put("/documents/default/focus", json={"on": False})
        assert recv(ws)["offer"]["id"] == offer["id"]
    assert len(client.get("/documents/default/offers").json()["offers"]) == 1


def test_tap_and_dismiss(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        open_gate(ws, clock)
        a = post(client, chunk)
        recv(ws)
        r = client.post(f"/offers/{a['id']}/tap")
        assert r.status_code == 200 and r.json()["status"] == "tapped" and r.json()["resolved_at"]
        upd = recv(ws)
        assert upd["type"] == "offer.updated" and upd["offer"]["status"] == "tapped"
    for verb in ("tap", "dismiss"):
        r = client.post(f"/offers/{a['id']}/{verb}")
        assert r.status_code == 409
        assert r.json()["detail"] == {"code": "invalid_transition", "status": "tapped"}
    assert client.post("/offers/nope/tap").status_code == 404
    assert client.get("/documents/nope/offers").status_code == 404
    r = client.post(
        "/documents/nope/offers",
        json={"kind": "k", "anchor_chunk": chunk, "reason": "x", "score": 0.5},
    )
    assert r.status_code == 404
    r = client.post(
        "/documents/default/offers",
        json={"kind": "k", "anchor_chunk": "nope", "reason": "x", "score": 0.5},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "anchor_unknown"


def test_held_offer_update_is_not_pushed(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        attend(ws, True)
        a = post(client, chunk)
        client.post(f"/offers/{a['id']}/dismiss")
        assert silent(ws)  # the browser never heard of it


def test_bad_attention_frames(client, chunk, clock):
    with client.websocket_connect(WS) as ws:
        for bad in (
            {"type": "attention", "pen": "yes"},
            {"type": "attention", "pen": False, "view": {"x": True}},
            {"type": "attention", "pen": False, "view": "x"},
        ):
            ws.send_json(bad)
            assert recv(ws)["type"] == "error"
        attend(ws, False)  # still open
        clock.t = 9
        post(client, chunk)
        attend(ws, False)
        assert recv(ws)["type"] == "offer.created"
