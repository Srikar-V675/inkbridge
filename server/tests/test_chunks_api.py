"""INK-033: canvases, chunk outline in reading order, deep links, overview and full-size crops."""

import io

from PIL import Image

from inkbridge import config
from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import arrow, rect

CHUNKS = "/documents/default/chunks"


def png(w, h, colour=(0, 0, 255)):
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, "PNG")
    return out.getvalue()


def upload(client, chunk_id, data):
    r = client.put(f"/regions/{chunk_id}/image", files={"image": ("c.png", data, "image/png")})
    assert r.status_code == 200, r.text


def page(client):
    # Two rows of two chunks plus a title; reading order: title, a, b, c, d.
    return Canvas(
        client,
        row("t", 3, x=0, y=0)
        + row("b", 3, x=600, y=205)
        + row("a", 3, x=0, y=200)
        + row("d", 3, x=600, y=400)
        + row("c", 3, x=0, y=410),
    )


def outline(client, **params):
    r = client.get(CHUNKS, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_chunks_come_in_reading_order_with_the_outline_fields(client):
    canvas = page(client)
    body = outline(client)
    assert body["document"] == "default" and body["version"] == canvas.version
    assert body["chunk_count"] == 5
    firsts = [c["element_ids"][0] for c in body["chunks"]]
    assert firsts == ["t0", "a0", "b0", "c0", "d0"]
    assert [c["order"] for c in body["chunks"]] == [1, 2, 3, 4, 5]
    c = body["chunks"][0]
    assert set(c) >= {
        "id", "order", "kind", "bounds", "text", "latex", "status", "links", "deep_link",
        "content_hash", "text_hash", "png_stale",
    }  # fmt: skip
    assert c["status"] == "active" and c["png_stale"] is True and c["text"] is None
    assert outline(client) == body  # stable across reads


def test_order_is_stable_across_saves_that_do_not_move_anything(client):
    canvas = page(client)
    before = [c["id"] for c in outline(client)["chunks"]]
    canvas.el("a1")["version"] = 9  # churn only
    canvas.put()
    assert [c["id"] for c in outline(client)["chunks"]] == before


def test_png_stale_filter_keeps_page_order_numbers(client):
    page(client)
    chunks = outline(client)["chunks"]
    upload(client, chunks[1]["id"], png(4, 4))
    stale = outline(client, png_stale=1)["chunks"]
    assert [c["order"] for c in stale] == [1, 3, 4, 5]
    fresh = outline(client, png_stale=0)["chunks"]
    assert [c["id"] for c in fresh] == [chunks[1]["id"]]


def test_orphaned_chunks_are_listed_on_request_without_an_order(client):
    canvas = Canvas(client, row("e", 3) + row("f", 3, y=500))
    gone = canvas.chunk_of("e0")
    for i in range(3):
        canvas.el(f"e{i}")["isDeleted"] = True
    canvas.put()
    assert [c["id"] for c in outline(client)["chunks"]] != [gone["id"]]
    (orphan,) = outline(client, status="orphaned")["chunks"]
    assert orphan["id"] == gone["id"] and orphan["order"] is None
    assert len(outline(client, status="all")["chunks"]) == 2
    assert client.get(CHUNKS, params={"status": "bogus"}).status_code == 422


def test_links_are_listed_on_the_chunk_they_leave(client):
    els = [
        rect("a", 0, 0, 100, 100),
        rect("b", 2000, 0, 100, 100),
        arrow("arr", 100, 50, 1900, start="a", end="b"),
    ]
    Canvas(client, els)
    a, b = outline(client)["chunks"]
    assert a["links"] == [{"to": b["id"], "kind": "arrow"}] and b["links"] == []


def test_deep_links_use_the_configured_base(client, monkeypatch):
    page(client)
    first = outline(client)["chunks"][0]
    assert config.DEFAULT_PUBLIC_URL == "http://localhost:5173"
    assert first["deep_link"] == f"http://localhost:5173/?canvas=default&chunk={first['id']}"
    monkeypatch.setenv("INKBRIDGE_PUBLIC_URL", "http://laptop.local:5173/")
    first = outline(client)["chunks"][0]
    assert first["deep_link"] == f"http://laptop.local:5173/?canvas=default&chunk={first['id']}"


def test_overview_respects_the_width_cap_and_draws_boxes_for_missing_crops(client):
    page(client)  # no crops uploaded yet: every chunk is a box
    r = client.get("/documents/default/overview", params={"max_width": 300})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert BLUE not in colours(r.content, max_width=300)
    for c in outline(client)["chunks"]:
        upload(client, c["id"], png(40, 20))
    r = client.get("/documents/default/overview", params={"max_width": 300})
    assert BLUE in colours(r.content, max_width=300)  # the crops are pasted in


BLUE = (0, 0, 255)


def colours(data, max_width):
    with Image.open(io.BytesIO(data)) as img:
        assert img.width <= max_width
        return {c for _, c in img.convert("RGB").getcolors(1 << 22)}


def test_overview_is_never_scaled_up_and_handles_empty_and_broken_crops(client):
    r = client.get("/documents/default/overview")
    assert r.status_code == 200  # empty canvas: a small blank image
    canvas = Canvas(client, row("a", 3))
    (c,) = canvas.chunks()
    _crop_path(c["id"]).write_bytes(b"not a png")  # drawn as a box, not a 500
    r = client.get("/documents/default/overview", params={"max_width": 4000})
    with Image.open(io.BytesIO(r.content)) as img:
        assert img.width < 200  # 55 px of ink plus padding, at scale 1


def _crop_path(region_id):
    path = config.crops_dir() / f"{region_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_region_png_returns_the_stored_bytes_unchanged(client):
    canvas = Canvas(client, row("a", 3))
    (c,) = canvas.chunks()
    assert client.get(f"/regions/{c['id']}/png").status_code == 404  # no crop yet
    data = png(3000, 40)  # wider than the /image cap
    upload(client, c["id"], data)
    r = client.get(f"/regions/{c['id']}/png")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png"
    assert client.get("/regions/nope/png").status_code == 404


def test_documents_can_be_created_and_listed(client, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_PUBLIC_URL", "http://laptop.local:5173")
    r = client.post("/documents", json={"title": "  Linear algebra  "})
    assert r.status_code == 201
    doc = r.json()
    assert doc["title"] == "Linear algebra" and len(doc["id"]) == 12 and doc["version"] == 0
    assert doc["url"] == f"http://laptop.local:5173/?canvas={doc['id']}"
    assert client.get(f"/documents/{doc['id']}/scene").json() == {"version": 0, "elements": []}
    assert outline_of(client, doc["id"])["chunks"] == []
    listed = client.get("/documents").json()
    assert {d["id"] for d in listed} == {"default", doc["id"]}
    for bad in ({"title": ""}, {"title": "   "}, {"title": "x" * 201}, {}):
        assert client.post("/documents", json=bad).status_code == 422


def outline_of(client, doc_id):
    return client.get(f"/documents/{doc_id}/chunks").json()


def test_unknown_document_is_404_with_a_next_step(client):
    for path in ("/documents/nope/chunks", "/documents/nope/overview"):
        r = client.get(path)
        assert r.status_code == 404
        assert "GET /documents" in r.json()["detail"]
