"""INK-132: detectors turn the canvas into offer candidates with no model."""


from inkbridge import db
from inkbridge.agent import detectors
from inkbridge.db import questions as q_db
from tests.test_chunk_persistence import Canvas, row
from tests.test_search import recognise


def scan():
    conn = db.connect()
    try:
        return detectors.scan(conn, "default")
    finally:
        conn.close()


def of_kind(kind):
    return [c for c in scan() if c.kind == kind]


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
