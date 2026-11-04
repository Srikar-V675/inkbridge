"""INK-078: accepted agent elements become their own chunks, read privately (decision 0044)."""

from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import rect

AGENT = {"author": "agent", "op_id": "op1"}
FAR = 2000


def text(i, x, y, op="op1", draft=False, **extra):
    cd = {"author": "agent", "op_id": op, **({"draft": True} if draft else {})}
    return {
        "id": i, "type": "text", "x": x, "y": y, "width": 80, "height": 25, "text": "hello",
        "fontSize": 20, "fontFamily": 1, "isDeleted": False, "version": 1, "customData": cd,
        **extra,
    }  # fmt: skip


def accept(canvas, ids):
    """What the browser's Accept does: drop customData.draft, bump version, delta save."""
    sent = []
    for e in canvas.elements:
        if e["id"] in ids:
            e["customData"] = {k: v for k, v in e["customData"].items() if k != "draft"}
            e["version"] += 1
            sent.append(e)
    r = canvas.client.put(
        "/documents/default/scene",
        json={"base_version": canvas.version, "elements": sent, "delta": True},
    )
    assert r.status_code == 200
    canvas.version = r.json()["version"]


def test_accepted_agent_text_gets_a_chunk_via_delta_save(client):
    canvas = Canvas(client, row("a", 5) + [text("op1:0", FAR, FAR, draft=True)])
    assert [c["element_ids"] for c in canvas.chunks()] == [["a0", "a1", "a2", "a3", "a4"]]
    accept(canvas, {"op1:0"})
    assert sorted(c["element_ids"] for c in canvas.chunks("active")) == [
        ["a0", "a1", "a2", "a3", "a4"],
        ["op1:0"],
    ]
    listed = client.get("/documents/default/chunks").json()
    assert any(c["element_ids"] == ["op1:0"] for c in listed["chunks"])


def test_accepted_diagram_is_one_chunk(client):
    def cd(e):
        return {**e, "customData": {**AGENT, "draft": True}, "version": 1, "isDeleted": False}

    elements = [
        cd(rect("op1:0", FAR, FAR)),
        cd(text("op1:1", FAR + 5, FAR + 5, containerId="op1:0")),
        cd(rect("op1:3", FAR + 200, FAR)),
        cd(
            {
                "id": "op1:2", "type": "arrow", "x": FAR + 100, "y": FAR + 25,
                "width": 100, "height": 0, "points": [[0, 0], [100, 0]],
                "startBinding": {"elementId": "op1:0"}, "endBinding": {"elementId": "op1:3"},
            }
        ),
    ]  # fmt: skip
    canvas = Canvas(client, row("a", 5) + elements)
    assert len(canvas.chunks("active")) == 1
    accept(canvas, {e["id"] for e in elements})
    assert sorted(canvas.chunk_of("op1:0")["element_ids"]) == [
        "op1:0", "op1:1", "op1:2", "op1:3",
    ]  # fmt: skip
