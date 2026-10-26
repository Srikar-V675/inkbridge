"""INK-034: read_canvas over MCP, the size cap, and search scoped to any canvas."""

import asyncio
import base64
import io
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import arrow, rect
from tests.test_search import recognise


@pytest.fixture
def api(client):
    server.set_client(ApiClient(client))
    yield client
    server.set_client(None)


def call(name, **args):
    return asyncio.run(server.mcp.call_tool(name, args))


def outline(result):
    return json.loads(result.content[0].text)


def test_read_canvas_returns_the_outline_then_the_overview_image(api):
    els = [
        rect("a", 0, 0, 100, 100),
        rect("b", 2000, 0, 100, 100),
        arrow("arr", 100, 50, 1900, start="a", end="b"),
    ]
    canvas = Canvas(api, els)
    a = canvas.chunk_of("a")
    recognise(a, "gradient descent")
    result = call("read_canvas")
    body = outline(result)
    assert body["document"] == "default" and body["version"] == canvas.version
    assert body["chunk_count"] == 2 and "omitted" not in body
    first, second = body["chunks"]
    assert first["id"] == a["id"] and first["order"] == 1 and first["text"] == "gradient descent"
    assert first["links"] == [{"to": second["id"], "kind": "arrow"}]
    assert first["deep_link"].endswith(f"/?canvas=default&chunk={a['id']}")
    assert second["text"] is None  # not read yet: the description says to open it with get_region
    assert set(first) == {
        "id", "order", "kind", "bounds", "text", "latex", "status", "png_stale",
        "content_hash", "links", "deep_link",
    }  # fmt: skip
    image = result.content[1]
    assert image.type == "image" and image.mime_type == "image/png"
    with Image.open(io.BytesIO(base64.b64decode(image.data))) as img:
        assert img.width <= 1024


def test_read_canvas_without_overview_and_tool_guidance(api):
    Canvas(api, row("a", 3))
    result = call("read_canvas", include_overview=False)
    assert len(result.content) == 1
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert "get_region" in tools["read_canvas"].description  # what to do with text: null


def test_read_canvas_reads_any_canvas_and_404s_with_a_next_step(api):
    doc = api.post("/documents", json={"title": "Second"}).json()["id"]
    assert outline(call("read_canvas", document_id=doc, include_overview=False))["chunks"] == []
    with pytest.raises(ToolError, match="document_id"):
        call("read_canvas", document_id="nope")


def _many_chunks(n):
    els = []
    for c in range(n):
        els += row(f"c{c}_", 2, x=(c % 20) * 400, y=(c // 20) * 200)
    return els


def test_200_chunk_canvas_stays_under_the_cap_and_says_what_was_omitted(api):
    canvas = Canvas(api, _many_chunks(200))
    for c in canvas.chunks()[:200]:
        recognise(c, "a fairly long line of handwriting " * 6)
    result = call("read_canvas", include_overview=False)
    text = result.content[0].text
    assert len(text) <= server.READ_CANVAS_MAX_CHARS
    body = json.loads(text)
    shown = len(body["chunks"])
    assert 0 < shown < 200 and body["chunk_count"] == 200
    assert body["omitted"] == 200 - shown
    assert f"offset={shown}" in body["note"]
    assert [c["order"] for c in body["chunks"]] == list(range(1, shown + 1))
    rest = outline(call("read_canvas", include_overview=False, offset=shown))
    assert rest["chunks"][0]["order"] == shown + 1
    later = outline(call("read_canvas", include_overview=False, offset=10))
    assert later["chunks"][0]["order"] == 11
    assert f"offset={10 + len(later['chunks'])}" in later["note"]  # counts from the given offset


def test_one_huge_reading_is_shortened_not_dropped(api):
    canvas = Canvas(api, row("a", 3))
    recognise(canvas.chunk_of("a0"), "x" * 100_000)
    result = call("read_canvas", include_overview=False)
    assert len(result.content[0].text) <= server.READ_CANVAS_MAX_CHARS
    (chunk,) = outline(result)["chunks"]
    assert chunk["text"].endswith("…") and chunk["text_truncated"] is True


def test_overview_failure_keeps_the_outline(api, monkeypatch):
    Canvas(api, row("a", 3))
    from inkbridge.mcp.client import ApiError

    def boom(*a, **k):
        raise ApiError("The Inkbridge API returned an error (500).")

    monkeypatch.setattr(server.get_client(), "get_overview", boom)
    result = call("read_canvas")
    assert outline(result)["chunk_count"] == 1
    assert "overview unavailable" in result.content[1].text and "500" in result.content[1].text


def test_get_region_accepts_chunk_ids(api):
    canvas = Canvas(api, row("a", 3))
    chunk = canvas.chunk_of("a0")
    result = call("get_region", region_id=chunk["id"], include_image=False)
    assert json.loads(result.content[0].text)["id"] == chunk["id"]


def test_search_finds_text_in_a_canvas_other_than_default(api):
    doc = api.post("/documents", json={"title": "Notes"}).json()["id"]
    elements = row("n", 3)
    r = api.put(f"/documents/{doc}/scene", json={"base_version": 0, "elements": elements})
    assert r.status_code == 200
    (chunk,) = api.get(f"/documents/{doc}/chunks").json()["chunks"]
    recognise(chunk, "eigenvalues")
    assert json.loads(call("search", query="eigen").content[0].text)["results"] == []
    hits = json.loads(call("search", query="eigen", document_id=doc).content[0].text)["results"]
    assert [h["region_id"] for h in hits] == [chunk["id"]]
