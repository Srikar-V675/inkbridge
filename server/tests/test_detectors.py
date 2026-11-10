"""INK-132: detectors turn the canvas into offer candidates with no model."""

import itertools

from inkbridge import db
from inkbridge.agent import detectors
from inkbridge.db import questions as q_db
from tests.test_chunk_persistence import Canvas, row, stroke
from tests.test_search import recognise


def scan(slow=True):
    conn = db.connect()
    try:
        return detectors.scan(conn, "default", slow=slow)
    finally:
        conn.close()


def of_kind(kind, slow=True):
    return [c for c in scan(slow) if c.kind == kind]


def chunks(client, *texts):
    """One chunk per text, rows 500 px apart, each read as the given text (None = no reading)."""
    canvas = Canvas(client, [e for i, _ in enumerate(texts) for e in row(f"r{i}", 3, y=500 * i)])
    out = []
    for i, t in enumerate(texts):
        c = canvas.chunk_of(f"r{i}0")
        if t is not None:
            recognise(c, t)
        out.append(canvas.chunk_of(f"r{i}0"))
    return canvas, out


def with_dots(client, n_real, n_dots, reading="w"):
    """n_real 3-element chunks plus n_dots single-element dots far apart; returns the canvas."""
    els = [e for i in range(n_real) for e in row(f"r{i}", 3, y=500 * i)]
    els += [stroke(f"dot{j}", 0, 500 * (n_real + j)) for j in range(n_dots)]
    canvas = Canvas(client, els)
    for i in range(n_real):
        recognise(canvas.chunk_of(f"r{i}0"), reading)
    return canvas


def test_tiny_chunk_never_triggers(client):
    canvas = with_dots(client, 1, 1, reading="Meeting notes")
    recognise(canvas.chunk_of("dot0"), "?")  # a dot read as a stray mark
    assert of_kind("question") == []
    chunks(client, "Why?")
    assert len(of_kind("question")) == 1


def test_question(client):
    _, (a, b, c) = chunks(client, "Why does it rise?", "what is a tensor", "Meeting notes")
    found = {x.anchor: x for x in of_kind("question")}
    assert set(found) == {a["id"], b["id"]}
    assert found[a["id"]].payload == {"action": "answer", "prepare": True, "key": a["text_hash"]}
    assert not [x for x in of_kind("question") if x.anchor == c["id"]]


def test_question_mark_ends_text(client):
    _, (a,) = chunks(client, "Done?")
    assert [x.anchor for x in of_kind("question")] == [a["id"]]


def test_open_equation(client):
    _, (a, _b) = chunks(client, "x + 2 =", "x = 2")
    (found,) = of_kind("open_equation")
    assert found.anchor == a["id"] and found.payload["action"] == "answer"
    assert found.payload["key"] == a["text_hash"]


def test_dangling_arrow(client):
    _, (a, _b) = chunks(client, "x", "y")
    conn = db.connect()
    conn.execute("UPDATE regions SET kind='connector' WHERE id=?", (a["id"],))
    conn.commit()
    conn.close()
    (found,) = of_kind("dangling_arrow")
    assert found.anchor == a["id"] and found.payload["action"] == "ask_user"
    assert found.payload["key"] == a["content_hash"]


def test_stale_note(client):
    canvas, (a,) = chunks(client, "reading A")
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(a["id"], a["text_hash"])])
    conn.close()
    assert of_kind("stale_note") == []
    recognise(a, "other words", source="user")
    new = canvas.chunk_of("r00")
    (found,) = of_kind("stale_note")
    assert found.anchor == a["id"]
    assert found.payload == {"action": "note", "note": "n1", "key": new["text_hash"]}
    assert new["text_hash"] != a["text_hash"]


def test_stale_note_ignores_unread_and_inactive(client):
    _, (a, _b) = chunks(client, None, "read")
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(a["id"], "f" * 64), ("gone00000000", "f" * 64)])
    conn.close()
    assert of_kind("stale_note") == []


def test_to_note(client):
    _, cs = chunks(client, *["w"] * 7)
    assert of_kind("to_note") == []
    _, cs = chunks(client, *["w"] * 8)
    (found,) = of_kind("to_note")
    assert found.payload == {"action": "note", "key": "canvas"}
    conn = db.connect()
    db.put_watch(conn, "default", "n1", [(cs[0]["id"], "f" * 64)])
    conn.close()
    assert of_kind("to_note") == []


def test_to_note_ignores_dots_in_the_count(client):
    with_dots(client, 7, 3)
    assert of_kind("to_note") == []


def test_to_note_once_per_canvas(client):
    canvas = with_dots(client, 8, 0)
    assert len(of_kind("to_note")) == 1
    canvas.elements += [stroke("dot9", 0, 99000)] + row("r9", 3, y=50000)
    canvas.put()
    assert len(of_kind("to_note")) == 1


def test_run_to_note_not_repeated_by_new_dot(client):
    canvas = with_dots(client, 8, 0)
    assert len([o for o in run(slow=True) if o["kind"] == "to_note"]) == 1
    canvas.elements += [stroke("dotx", 0, 99000)]
    canvas.put()
    assert len([o for o in run(slow=True) if o["kind"] == "to_note"]) == 1


def _flow(n_boxes, n_arrows):
    """n_boxes rectangles 300 apart on a line, native arrows joining neighbours."""
    els = [
        {
            "id": f"box{i}",
            "type": "rectangle",
            "x": 300 * i,
            "y": 0,
            "width": 100,
            "height": 60,
            "version": 1,
        }
        for i in range(n_boxes)
    ]
    for i in range(n_arrows):
        els.append(
            {
                "id": f"arr{i}",
                "type": "arrow",
                "x": 300 * i + 100,
                "y": 30,
                "width": 200,
                "height": 0,
                "points": [[0, 0], [200, 0]],
                "endArrowhead": "arrow",
                "startBinding": {"elementId": f"box{i}", "focus": 0, "gap": 1},
                "endBinding": {"elementId": f"box{i + 1}", "focus": 0, "gap": 1},
                "version": 1,
            }
        )
    return els


def test_sketch(client):
    Canvas(client, _flow(3, 2))
    (found,) = of_kind("sketch")
    assert found.payload["action"] == "diagram" and found.reason == "Draw this cleanly"
    conn = db.connect()
    assert db.get_region(conn, found.anchor)["status"] == "active"
    conn.close()


def test_sketch_needs_three_nodes_and_two_arrows(client):
    Canvas(client, _flow(2, 1))
    assert of_kind("sketch") == []


def _doc(client, title):
    return client.post("/documents", json={"title": title}).json()["id"]


def test_related(client, monkeypatch):
    other = _doc(client, "B")
    (a,) = Canvas(client, row("a", 3)).chunks()
    # a chunk in document B, put there through the same scene API
    scene_b = f"/documents/{other}/scene"
    els = row("b", 3)
    client.put(
        scene_b, json={"base_version": client.get(scene_b).json()["version"], "elements": els}
    )
    conn = db.connect()
    (b,) = db.list_regions(conn, other, chunks=True, status="active")
    db.save_recognition(
        conn, b["id"], b["content_hash"], "gemini", "gradient descent learning rate"
    )
    conn.close()

    recognise(a, "choosing a learning rate for gradient descent")
    monkeypatch.setattr(detectors, "RELATED_MIN_SCORE", 0)
    (found,) = of_kind("related")
    assert found.anchor == a["id"]
    assert found.payload == {
        "action": "link",
        "other_document": other,
        "other_chunk": b["id"],
        "key": b["id"],
    }

    recognise(a, "completely different pottery glaze", source="user")
    assert of_kind("related") == []  # nothing shares a token, even at threshold 0

    monkeypatch.setattr(detectors, "RELATED_MIN_SCORE", 99)
    recognise(a, "choosing a learning rate for gradient descent", source="user")
    assert of_kind("related") == []  # default-style high bar


def test_related_finds_a_past_answer(client, monkeypatch):
    (a,) = Canvas(client, row("a", 3)).chunks()
    conn = db.connect()
    q = q_db.create_question(conn, "default", "what is momentum", [], None)
    q_db.answer_question(conn, q["id"], "momentum smooths gradient descent updates", [])
    conn.close()
    recognise(a, "gradient descent with momentum")
    monkeypatch.setattr(detectors, "RELATED_MIN_SCORE", 0)
    (found,) = of_kind("related")
    assert found.payload["other_question"] == q["id"] and found.payload["action"] == "link"


def run(**kw):
    conn = db.connect()
    try:
        detectors.run(conn, "default", **kw)
        return db.offers.list_offers(conn, "default")
    finally:
        conn.close()


def test_run_creates_offers_and_dedupes(client):
    _, (a,) = chunks(client, "Why is it so?")
    (o,) = run()
    assert (o["source"], o["kind"], o["anchor_chunk"], o["status"]) == (
        "detector",
        "question",
        a["id"],
        "open",
    )
    assert o["reason"] and run() == [o]
    conn = db.connect()
    db.offers.dismiss_offer(conn, o["id"])
    conn.close()
    assert len(run()) == 1  # a dismissed offer does not come back
    recognise(a, "Why would it fall?", source="user")
    assert len(run()) == 2  # new reading, new key


def test_run_swallows_budget_refusals(client):
    chunks(client, *["Why a?", "Why b?", "Why c?", "Why d?"])
    assert len(run()) == 1  # four candidates, one chip: the rest wait for a later scan


def test_scan_now_publishes(client, monkeypatch):
    from inkbridge.agent import attention as attention_mod
    from inkbridge.api import offers as offers_api
    from tests.test_offers_api import WS, Clock, open_gate, recv

    monkeypatch.setenv("INKBRIDGE_QUIET_S", "8")
    clock = Clock()
    monkeypatch.setattr(attention_mod.attention, "clock", clock)
    monkeypatch.setattr(offers_api, "_ARM_TIMERS", False)
    offers_api.pushed.clear()
    offers_api._seen_session.clear()
    chunks(client, "Why is it so?")
    with client.websocket_connect(WS) as ws:
        open_gate(ws, clock)
        offers_api.scan_now("default")
        msg = recv(ws)
    assert msg["type"] == "offer.created" and msg["offer"]["kind"] == "question"


def test_scan_now_survives_a_detector_bug(client, monkeypatch):
    from inkbridge.api import offers as offers_api

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(detectors, "scan", boom)
    offers_api.scan_now("default")  # logged, not raised


def test_save_triggers_scan(client, monkeypatch):
    from inkbridge.api import offers as offers_api

    calls = []
    monkeypatch.setattr(offers_api, "schedule_scan", calls.append)
    canvas = Canvas(client, row("a", 3))
    assert calls == ["default"]
    canvas.put()  # nothing changed
    assert calls == ["default"]


def test_no_model_in_detectors():
    import ast
    from pathlib import Path

    banned = ("inkbridge.recognizer", "google", "httpx", "anthropic", "requests", "urllib")
    tree = ast.parse(Path(detectors.__file__).read_text())
    for n in ast.walk(tree):
        names = (
            [a.name for a in n.names]
            if isinstance(n, ast.Import)
            else [n.module or ""]
            if isinstance(n, ast.ImportFrom)
            else []
        )
        assert not [x for x in names if x.startswith(banned)], names
        if isinstance(n, ast.ImportFrom):
            assert not [a for a in n.names if a.name == "genai"]


def test_expired_offer_can_return(client):
    chunks(client, "Why is it so?")
    (o,) = run()
    conn = db.connect()
    conn.execute("UPDATE offers SET status='expired' WHERE id=?", (o["id"],))
    conn.commit()
    conn.close()
    assert len(run()) == 2  # an expired offer is not a refusal


def test_concurrent_scans_do_not_duplicate(client):
    from concurrent.futures import ThreadPoolExecutor

    from inkbridge.api import offers as offers_api

    chunks(client, "Why is it so?")
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: offers_api.scan_now("default"), range(4)))
    assert len(run()) == 1


def test_scan_logs_why_nothing(client, monkeypatch, caplog):
    import logging

    from inkbridge.api import offers as offers_api

    monkeypatch.setattr(offers_api, "_ARM_TIMERS", False)
    Canvas(client, row("a", 3) + row("b", 3, y=500))
    caplog.set_level(logging.INFO, logger="inkbridge.offers")
    offers_api.scan_now("default")
    msgs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("scan doc=")]
    assert len(msgs) == 1
    assert "chunks=2" in msgs[0] and "unread=2" in msgs[0] and "candidates=0" in msgs[0]


def test_run_logs_refusals(client, caplog):
    import logging

    _, (_a, b, c, d) = chunks(client, "Why a?", "plain b", "plain c", "plain d")
    conn = db.connect()
    for x in (b, c, d):
        db.offers.create_offer(
            conn, "default", kind="related", anchor_chunk=x["id"], reason="r",
            payload={"key": x["id"]}, score=1.0, source="detector", session_start="",
        )
    conn.close()
    caplog.set_level(logging.INFO, logger="inkbridge.offers")
    run()
    msgs = [r.getMessage() for r in caplog.records if "detector run" in r.getMessage()]
    assert len(msgs) == 1 and "held=open_offer" in msgs[0]  # one chip on screen: nothing new
    assert len([o for o in run() if o["kind"] == "question"]) == 0


def _box(i, x, y=0):
    return {"id": i, "type": "rectangle", "x": x, "y": y, "width": 100, "height": 60, "version": 1}


def _free_arrow(**extra):
    return {
        "id": "arr0",
        "type": "arrow",
        "x": 100,
        "y": 30,
        "width": 200,
        "height": 0,
        "points": [[0, 0], [200, 0]],
        "endArrowhead": "arrow",
        "startBinding": {"elementId": "box0", "focus": 0, "gap": 1},
        "version": 1,
        **extra,
    }


def _arrow_canvas(client, arrow, *others):
    return Canvas(client, [_box("box0", 0), *row("t", 3, x=10, y=20), arrow, *others])


def test_dangling_arrow_v1(client):
    _arrow_canvas(client, _free_arrow())
    (found,) = of_kind("dangling_arrow")
    assert found.payload == {"action": "ask_user", "key": "arr0"}
    conn = db.connect()
    assert db.get_region(conn, found.anchor)["status"] == "active"
    conn.close()


def test_dangling_arrow_v1_negatives(client):
    bound = _free_arrow(endBinding={"elementId": "box1", "focus": 0, "gap": 1})
    _arrow_canvas(client, bound, _box("box1", 300))
    assert of_kind("dangling_arrow") == []


def test_dangling_arrow_v1_ends_near_a_box(client):
    _arrow_canvas(client, _free_arrow(), _box("box1", 320))  # 20 units from the tip
    assert of_kind("dangling_arrow") == []


def test_dangling_arrow_v1_ignores_drafts(client):
    _arrow_canvas(client, _free_arrow(customData={"draft": True}))
    assert of_kind("dangling_arrow") == []


def test_dangling_arrow_v1_ignores_deleted(client):
    _arrow_canvas(client, _free_arrow(isDeleted=True))
    assert of_kind("dangling_arrow") == []


def _loop(i, x, y=0, w=120, h=80):
    pts = [[0, 0], [w, 0], [w, h], [0, h], [0, 0]]
    dense = []
    for a, b in itertools.pairwise(pts):
        dense += [[a[0] + (b[0] - a[0]) * t / 6, a[1] + (b[1] - a[1]) * t / 6] for t in range(6)]
    dense.append([0, 0])
    return {
        "id": i, "type": "freedraw", "x": x, "y": y, "width": w, "height": h, "angle": 0,
        "points": dense, "pressures": [0.5] * len(dense), "simulatePressure": False, "version": 1,
    }  # fmt: skip


def _pen_arrow(i, x, y=40):
    pts = [[0, 0], [60, 1], [120, 0], [170, 0], [158, -10]]
    return {
        "id": i, "type": "freedraw", "x": x, "y": y, "width": 170, "height": 10, "angle": 0,
        "points": pts, "pressures": [0.5] * len(pts), "simulatePressure": False, "version": 1,
    }  # fmt: skip


def _pen_flow(y=0):
    return [
        _loop("p0", 0, y), _loop("p1", 300, y), _loop("p2", 600, y),
        _pen_arrow("pa0", 125, y + 40), _pen_arrow("pa1", 425, y + 40),
    ]  # fmt: skip


def test_sketch_pen_drawn(client):
    Canvas(client, _pen_flow())
    assert len(of_kind("sketch")) == 1


def _put(client, doc, els):
    scene = f"/documents/{doc}/scene"
    client.put(scene, json={"base_version": client.get(scene).json()["version"], "elements": els})


def _read(doc, text):
    conn = db.connect()
    try:
        (c,) = [c for c in db.list_regions(conn, doc, chunks=True, status="active") if c["element_ids"]]
        db.save_recognition(conn, c["id"], c["content_hash"], "gemini", text)
    finally:
        conn.close()


def test_one_offer_per_kind_via_run(client):
    q, arrow, flow = _doc(client, "Q"), _doc(client, "A"), _doc(client, "F")
    _put(client, q, row("q", 3))
    _read(q, "Why does ice float?")
    _put(client, arrow, [_box("box0", 0), *row("t", 3, x=10, y=20), _free_arrow()])
    _put(client, flow, _pen_flow())
    for _ in range(2):
        conn = db.connect()
        for d in (q, arrow, flow):
            detectors.run(conn, d)
        got = {d: [o["kind"] for o in db.offers.list_offers(conn, d)] for d in (q, arrow, flow)}
        conn.close()
        assert got[q] == ["question"]
        assert got[arrow] == ["dangling_arrow"]
        assert got[flow] == ["sketch"]


def _age(chunk_id, seconds):
    from datetime import UTC, datetime, timedelta

    conn = db.connect()
    conn.execute(
        "UPDATE regions SET updated_at=? WHERE id=?",
        ((datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(), chunk_id),
    )
    conn.commit()
    conn.close()


def test_old_ink_gives_no_offer(client):
    _, (a, b) = chunks(client, "Why does it rise?", "x =")
    assert of_kind("question") and of_kind("open_equation")
    _age(a["id"], 600)
    _age(b["id"], 600)
    assert of_kind("question") == [] and of_kind("open_equation") == []


def test_related_and_to_note_only_on_request(client, monkeypatch):
    other = _doc(client, "B")
    _put(client, other, row("b", 3))
    conn = db.connect()
    (b,) = db.list_regions(conn, other, chunks=True, status="active")
    db.save_recognition(conn, b["id"], b["content_hash"], "gemini", "gradient descent learning rate")
    conn.close()
    with_dots(client, 9, 0, reading="choosing a learning rate for gradient descent")
    monkeypatch.setattr(detectors, "RELATED_MIN_SCORE", 0)
    assert of_kind("to_note", slow=False) == [] and of_kind("related", slow=False) == []
    assert of_kind("to_note") and of_kind("related")  # on the slow path they still exist


def test_dangling_needs_arrowhead(client):
    _arrow_canvas(client, _free_arrow(endArrowhead=None, points=[[0, 0], [500, 0]], width=500))
    assert of_kind("dangling_arrow") == []


def test_dangling_short_arrow_ignored(client):
    _arrow_canvas(client, _free_arrow(points=[[0, 0], [100, 0]], width=100))
    assert of_kind("dangling_arrow") == []


def test_dangling_curvy_arrow_ignored(client):
    pts = [[0, 0], [100, 80], [200, -80], [300, 0]]
    _arrow_canvas(client, _free_arrow(points=pts, width=300))
    assert of_kind("dangling_arrow") == []


def test_dangling_freedraw_stroke_ignored(client):
    _arrow_canvas(client, _pen_arrow("pa0", 100, 30))
    assert of_kind("dangling_arrow") == []


def test_dangling_tip_near_a_box_ignored(client):
    _arrow_canvas(client, _free_arrow(), _box("box1", 360))  # tip 60 from a box: touching enough
    assert of_kind("dangling_arrow") == []


def test_dangling_tip_far_from_boxes_found(client):
    _arrow_canvas(client, _free_arrow())  # tip 200 from every box, straight, long, headed
    assert len(of_kind("dangling_arrow")) == 1


def test_run_creates_one_offer_at_a_time(client):
    chunks(client, "Why a?", "Why b?", "Why c?")
    assert len(run()) == 1  # three questions, one chip on screen
    assert len(run()) == 1  # still one while it is open
    conn = db.connect()
    db.offers.dismiss_offer(conn, run()[0]["id"])
    conn.close()
    later = [o for o in run() if o["status"] == "open"]
    assert len(later) == 1 and len(run()) == 2  # the next question, not the dismissed one


def test_flowchart_gives_at_most_one(client):
    free = {**_free_arrow(), "id": "free", "y": 230}
    Canvas(client, _flow(3, 2) + [free])
    assert len([o for o in run() if o["status"] == "open"]) == 1
