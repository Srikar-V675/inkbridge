"""INK-034: read_canvas over MCP, the size cap, and search scoped to any canvas."""

import asyncio
import base64
import io
import json
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image

from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from inkbridge.mcp.tools import canvas as canvas_tools
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
    assert first["links"] == [
        {"to": second["id"], "kind": "arrow", "label": None, "confidence": None}
    ]
    assert first["group_id"] == second["group_id"] == first["id"]
    assert body["groups"] == [{"id": first["id"], "chunk_ids": [first["id"], second["id"]]}]
    assert first["deep_link"].endswith(f"/?canvas=default&chunk={a['id']}")
    assert second["text"] is None  # not read yet: the description says to open it with get_region
    assert set(first) == {
        "id", "order", "kind", "bounds", "text", "latex", "status", "png_stale",
        "content_hash", "text_hash", "links", "group_id", "deep_link", "read_status", "read_note",
    }  # fmt: skip
    image = result.content[1]
    assert image.type == "image" and image.mime_type == "image/png"
    with Image.open(io.BytesIO(base64.b64decode(image.data))) as img:
        assert img.width <= 1568  # the read_canvas default width (INK-086)


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
    assert len(text) <= canvas_tools.READ_CANVAS_MAX_CHARS
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
    assert len(result.content[0].text) <= canvas_tools.READ_CANVAS_MAX_CHARS
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


class FakeCanvas(ApiClient):
    """An ApiClient whose /chunks reply is given, for shapes the real canvas makes slowly."""

    def __init__(self, http, chunks):
        super().__init__(http)
        self.chunks = chunks

    def get_chunks(self, document_id):
        return {
            "document": "default",
            "version": 1,
            "chunk_count": len(self.chunks),
            "chunks": self.chunks,
        }


def _chunk(i, **over):
    return {
        "id": f"c{i}", "order": i + 1, "kind": "handwriting",
        "bounds": {"x": 0, "y": i, "width": 1, "height": 1}, "text": None, "latex": None,
        "status": "active", "png_stale": False, "content_hash": "h" * 64, "links": [],
        "deep_link": f"http://x/?canvas=default&chunk=c{i}", **over,
    }  # fmt: skip


def test_a_chunk_with_thousands_of_links_is_capped_and_paging_moves_on(client):
    links = [{"to": f"t{j:05d}", "kind": "arrow"} for j in range(1500)]
    many = [_chunk(i, links=links) for i in range(80)]
    server.set_client(FakeCanvas(client, many))
    try:
        offset, seen = 0, []
        while True:
            text = call("read_canvas", include_overview=False, offset=offset).content[0].text
            assert len(text) <= canvas_tools.READ_CANVAS_MAX_CHARS
            body = json.loads(text)
            assert body["chunks"], "every page shows at least one chunk"
            for c in body["chunks"]:
                assert len(c["links"]) == canvas_tools.MAX_LINKS and c["links_omitted"] == 1480
            seen += [c["id"] for c in body["chunks"]]
            if "note" not in body:
                break
            assert "include_overview=false" in body["note"]
            offset += len(body["chunks"])
        assert seen == [c["id"] for c in many]
    finally:
        server.set_client(None)


def test_long_latex_is_shortened_too(client):
    server.set_client(FakeCanvas(client, [_chunk(0, latex="\\\\frac{a}{b}" * 2000)]))
    try:
        (c,) = outline(call("read_canvas", include_overview=False))["chunks"]
        assert c["latex_truncated"] is True and len(c["latex"]) == canvas_tools.MAX_READING_CHARS
    finally:
        server.set_client(None)


def test_offset_past_the_end_and_overview_of_an_empty_canvas(api):
    result = call("read_canvas", offset=50)
    body = outline(result)
    assert body["chunks"] == [] and "note" not in body and body["chunk_count"] == 0
    assert result.content[1].type == "image"  # the API's blank overview still arrives


def test_read_canvas_lists_only_active_chunks(api):
    from tests.test_regions_api import _orphan

    Canvas(api, [rect("a", 0, 0, 100, 100), rect("b", 5000, 0, 100, 100)])
    before = outline(call("read_canvas"))
    gone = before["chunks"][0]["id"]
    _orphan(gone)
    after = outline(call("read_canvas"))
    assert gone not in [c["id"] for c in after["chunks"]] and "version" in after


def _spread(n_cols, n_rows):
    # Far-apart 250 px boxes, one chunk each, in reading order: a canvas written while zoomed in.
    return [
        rect(f"r{r}_{c}", c * 4000, r * 3000, 250, 250)
        for r in range(n_rows)
        for c in range(n_cols)
    ]


def _images(result):
    return [c for c in result.content if c.type == "image"]


def _widths(result):
    widths = []
    for image in _images(result):
        with Image.open(io.BytesIO(base64.b64decode(image.data))) as img:
            widths.append(img.width)
    return widths


def test_read_canvas_splits_a_spread_canvas_into_several_overview_images(api):
    canvas = Canvas(api, _spread(10, 6))  # 60 chunks
    assert len(canvas.chunks()) == 60
    result = call("read_canvas")
    images = _images(result)
    assert 1 < len(images) <= 3
    assert all(w <= 1568 for w in _widths(result))
    note = result.content[-1].text  # the continuation line comes after the images
    shown_to = int(re.search(r"offset=(\d+)", note).group(1))
    assert "of 60" in note and 0 < shown_to < 60
    rest = outline(call("read_canvas", include_overview=False, offset=shown_to))
    assert rest["chunks"][0]["order"] == shown_to + 1
    more = call("read_canvas", offset=shown_to)
    assert _images(more) and _widths(more)[0] <= 1568


def test_read_canvas_max_width_is_passed_and_bounded(api):
    Canvas(api, _spread(5, 4))
    narrow = call("read_canvas", max_width=600)
    assert narrow.content and all(w <= 600 for w in _widths(narrow))
    with pytest.raises(Exception) as refused:  # the schema bound, before any API call
        call("read_canvas", max_width=5000)
    assert "less than or equal to 1568" in str(refused.value)


def test_read_canvas_past_the_end_still_returns_one_blank_image(api):
    Canvas(api, _spread(2, 2))
    result = call("read_canvas", offset=999)
    assert len(_images(result)) == 1 and _widths(result)[0] > 0


def test_read_canvas_doc_says_overview_is_orientation_only(api):
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    description = tools["read_canvas"].description
    assert "orientation" in description and "get_region" in description


def test_a_too_large_chunk_says_so_and_no_image_is_fetched(api, monkeypatch):
    canvas = Canvas(api, row("a", 3) + [rect("big", 0, 2000, w=5000, h=50)])
    chunks = {c["id"]: c for c in outline(call("read_canvas", include_overview=False))["chunks"]}
    big_id, a_id = canvas.chunk_of("big")["id"], canvas.chunk_of("a0")["id"]
    assert chunks[a_id]["read_status"] == "ok" and chunks[a_id]["read_note"] is None
    assert chunks[big_id]["read_status"] == "too_large" and "split" in chunks[big_id]["read_note"]

    def boom(self, region_id):
        raise AssertionError("an unreadable crop must not be fetched")

    monkeypatch.setattr(ApiClient, "get_image", boom)
    result = call("get_region", region_id=canvas.chunk_of("big")["id"])
    meta = json.loads(result.content[0].text)
    assert meta["read_status"] == "too_large"
    assert [c.type for c in result.content] == ["text", "text"]
    assert "split" in result.content[1].text
    ok = call("get_region", region_id=canvas.chunk_of("a0")["id"], include_image=False)
    assert json.loads(ok.content[0].text)["read_status"] == "ok"


def test_read_canvas_groups_are_capped(client):
    groups = [
        {"id": f"g{i:02d}", "chunk_ids": [f"g{i:02d}_{j:02d}" for j in range(30)]}
        for i in range(50)
    ]

    class WithGroups(FakeCanvas):
        def get_chunks(self, document_id):
            return {**super().get_chunks(document_id), "groups": groups}

    server.set_client(WithGroups(client, [_chunk(0)]))
    try:
        result = call("read_canvas", include_overview=False)
        text = result.content[0].text
        assert len(text) <= canvas_tools.READ_CANVAS_MAX_CHARS
        body = json.loads(text)
        assert len(body["groups"]) == canvas_tools.MAX_GROUPS
        assert body["groups_omitted"] == 50 - canvas_tools.MAX_GROUPS
        for g in body["groups"]:
            assert len(g["chunk_ids"]) == canvas_tools.MAX_GROUP_IDS
            assert g["omitted_ids"] == 30 - canvas_tools.MAX_GROUP_IDS
    finally:
        server.set_client(None)
