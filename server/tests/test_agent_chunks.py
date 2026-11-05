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


# --- Task 2: per-op groups in the pure chunker ---------------------------------------------------
from inkbridge.canvas.chunker import chunk_scene
from inkbridge.canvas.hashes import content_hash
from tests.test_chunker import stroke


def accepted(i, x, y, op="op1", **extra):
    return text(f"{op}:{i}", x, y, op=op, **extra)


def test_agent_text_beside_handwriting_is_its_own_chunk():
    els = [stroke(f"s{i}", 15 * i, 0) for i in range(5)] + [accepted(0, 90, 0)]
    assert sorted(chunk_scene(els).chunks) == [["op1:0"], ["s0", "s1", "s2", "s3", "s4"]]


def test_one_chunk_per_op_and_one_op_is_one_chunk():
    els = [accepted(0, 0, 0), accepted(1, 90, 0), accepted(0, 200, 0, op="op2")]
    assert chunk_scene(els).chunks == [["op1:0", "op1:1"], ["op2:0"]]


def test_draft_still_yields_no_chunk():
    assert chunk_scene([accepted(0, 0, 0, draft=True)]).chunks == []


def test_forged_tag_with_wrong_id_prefix_is_user_ink():
    forged = {**text("mine", 90, 0), "customData": AGENT}
    els = [stroke(f"s{i}", 15 * i, 0) for i in range(5)] + [forged]
    assert len(chunk_scene(els).chunks) == 1


def test_agent_groups_are_not_pinned():
    els = [stroke("s0", 0, 0), stroke("s1", 15, 0), accepted(0, 40, 0)]
    c = chunk_scene(els)
    assert c.pinned == [False, False] and len(c.chunks) == 2


def test_manual_pin_wins_over_agent_group():
    els = [stroke("s0", 0, 0), accepted(0, 40, 0), accepted(1, 400, 0)]
    c = chunk_scene(els, pins=[["s0", "op1:0"]])
    assert sorted(c.chunks) == [["op1:0", "s0"], ["op1:1"]]
    assert sorted(c.pinned) == [False, True]


def test_custom_data_stays_out_of_the_content_hash():
    plain = {k: v for k, v in accepted(0, 0, 0).items() if k != "customData"}
    assert content_hash([plain]) == content_hash([accepted(0, 0, 0)])


# --- Task 3: the agent reads its own chunk, no model call ----------------------------------------
from inkbridge.recognizer.worker import RecognitionWorker
from tests.test_recognition_worker import FakeModel, upload
from tests.test_search import recognise


def agent_chunk(canvas):
    return canvas.chunk_of("op1:0")


def test_accepted_text_is_read_without_a_model_call(client):
    canvas = Canvas(client, row("a", 5) + [text("op1:0", FAR, FAR, draft=True)])
    accept(canvas, {"op1:0"})
    chunk = agent_chunk(canvas)
    assert (chunk["text"], chunk["source"]) == ("hello", "agent")
    for c in canvas.chunks("active"):
        upload(client, canvas, c["id"])
    model = FakeModel()
    assert RecognitionWorker(model, ("default",), clock=lambda: 10**10).run_once() == 1
    assert len(model.calls) == 1  # the handwriting chunk only
    assert canvas.chunk_of("a0")["source"] == "gemini" and agent_chunk(canvas)["source"] == "agent"


def test_editing_the_agent_text_rereads_it(client):
    canvas = Canvas(client, [text("op1:0", 0, 0, draft=True)])
    accept(canvas, {"op1:0"})
    canvas.el("op1:0")["text"] = "bye"
    canvas.el("op1:0")["version"] += 1
    canvas.put()
    assert agent_chunk(canvas)["text"] == "bye"


def test_shape_only_diagram_reads_empty_and_a_user_reading_wins(client):
    shape = {**rect("op1:0", 0, 0), "customData": AGENT, "version": 1, "isDeleted": False}
    canvas = Canvas(client, [shape])
    chunk = agent_chunk(canvas)
    assert (chunk["text"], chunk["source"]) == ("", "agent")
    recognise(chunk, "mine", source="user")
    assert agent_chunk(canvas)["text"] == "mine"


def test_reject_removes_only_its_own_agent_chunk(client):
    canvas = Canvas(client, row("a", 5) + [text("op1:0", FAR, FAR, draft=True)])
    accept(canvas, {"op1:0"})
    user = canvas.chunk_of("a0")
    canvas.el("op1:0")["isDeleted"] = True  # what rejectOp does to the op's elements
    canvas.el("op1:0")["version"] += 1
    canvas.put()
    assert [c["id"] for c in canvas.chunks("active")] == [user["id"]]
    assert canvas.chunk_of("a0")["content_hash"] == user["content_hash"]


def test_mixed_chunks_get_no_agent_reading(client):
    """Limit pinned (decision 0044): a chunk with any user ink is not read as agent ink."""
    from tests.test_chunker import arrow

    shape = {**rect("op1:0", 0, 0), "customData": AGENT, "version": 1, "isDeleted": False}
    user_arrow = arrow("ua", 100, 25, 100, start="op1:0")  # user arrow starting at the shape
    canvas = Canvas(client, [shape, user_arrow])
    chunk = canvas.chunk_of("op1:0")
    assert "ua" in chunk["element_ids"] and chunk["source"] is None  # a Gemini candidate

    # a manual merge of agent and user ink is not all-agent either
    canvas = Canvas(client, [text("op1:0", 0, 0), *row("u", 3, x=3000, y=3000)])
    ids = [c["id"] for c in canvas.chunks("active")]
    r = client.post("/documents/default/chunks/merge", json={"chunk_ids": ids})
    assert r.status_code == 200, r.text
    merged = canvas.chunk_of("op1:0")
    assert "u0" in merged["element_ids"] and merged["source"] is None


def test_empty_agent_reading_passes_through_mcp(client):
    from inkbridge.mcp import server
    from inkbridge.mcp.client import ApiClient
    from tests.test_mcp_read_canvas import call, outline

    server.set_client(ApiClient(client))
    try:
        shape = {**rect("op1:0", 0, 0), "customData": AGENT, "version": 1, "isDeleted": False}
        Canvas(client, [shape])
        (chunk,) = outline(call("read_canvas", include_overview=False))["chunks"]
        assert chunk["text"] == ""
    finally:
        server.set_client(None)
