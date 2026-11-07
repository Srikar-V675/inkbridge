"""INK-118: canvases home (summaries, patch, open, duplicate) and the thumbnail cache."""

import json
import shutil

from inkbridge import db
from inkbridge.db import outline
from tests.test_chunk_persistence import row

HOME_KEYS = {
    "id", "title", "updated_at", "version", "url", "pinned", "archived", "element_count",
    "chunk_count", "open_offers", "last_opened_at",
}  # fmt: skip


def new_canvas(client, title="Sketch"):
    r = client.post("/documents", json={"title": title})
    assert r.status_code == 201
    return r.json()["id"]


def save(client, doc, elements, version=None):
    if version is None:
        version = client.get(f"/documents/{doc}/scene").json()["version"]
    r = client.put(f"/documents/{doc}/scene", json={"base_version": version, "elements": elements})
    assert r.status_code == 200
    return r.json()["version"]


def listing(client, **params):
    return {d["id"]: d for d in client.get("/documents", params=params).json()}


def ink_with_noise():
    return [
        *row("a", 3),
        {**row("x", 1, y=900)[0], "isDeleted": True},
        {**row("d", 1, y=1800)[0], "customData": {"draft": True, "author": "agent"}},
    ]


def test_list_has_home_fields(client):
    doc = new_canvas(client)
    save(client, doc, ink_with_noise())
    r = client.post(f"/documents/{doc}/ops", json={"type": "write_text", "payload": {"text": "hi"}})
    assert r.status_code == 201
    d = listing(client)[doc]
    assert set(d) == HOME_KEYS
    assert d["element_count"] == 3 and d["open_offers"] == 1
    assert d["pinned"] is False and d["archived"] is False and d["last_opened_at"] is None
    assert d["chunk_count"] >= 1 and d["version"] == 1
    assert set(client.post("/documents", json={"title": "y"}).json()) == HOME_KEYS


def test_patch_title_pin_archive_restore(client):
    doc = new_canvas(client)
    before = listing(client)[doc]["updated_at"]
    url = f"/documents/{doc}"
    r = client.patch(url, json={"title": "  New  "})
    assert r.status_code == 200 and r.json()["title"] == "New" and set(r.json()) == HOME_KEYS
    assert client.patch(url, json={"pinned": True}).json()["pinned"] is True
    assert client.patch(url, json={"archived": True}).json()["archived"] is True
    assert doc not in listing(client)
    assert doc in listing(client, archived="true") and doc in listing(client, archived="all")
    assert listing(client, archived="all")[doc]["updated_at"] == before

    def archived_at():
        return (
            db.connect()
            .execute("SELECT archived_at FROM documents WHERE id = ?", (doc,))
            .fetchone()[0]
        )

    first = archived_at()
    assert first is not None
    client.patch(url, json={"archived": True})
    assert archived_at() == first
    assert client.patch(url, json={"archived": False}).json()["archived"] is False
    assert doc in listing(client) and archived_at() is None
    assert client.patch(url, json={}).status_code == 422
    assert client.patch(url, json={"title": "   "}).status_code == 422
    assert client.patch("/documents/nope", json={"pinned": True}).status_code == 404


def test_open_stamps_last_opened(client):
    doc = new_canvas(client)
    client.get(f"/documents/{doc}/scene")
    assert listing(client)[doc]["last_opened_at"] is None
    assert client.post(f"/documents/{doc}/open").status_code == 204
    assert listing(client)[doc]["last_opened_at"] is not None
    assert client.post("/documents/nope/open").status_code == 404


def test_duplicate(client, monkeypatch):
    doc = new_canvas(client, "Plan")
    save(client, doc, ink_with_noise())
    client.post(f"/documents/{doc}/ops", json={"type": "write_text", "payload": {"text": "hi"}})
    src = listing(client)[doc]
    r = client.post(f"/documents/{doc}/duplicate")
    assert r.status_code == 201
    copy = r.json()
    assert copy["title"] == "Plan copy" and copy["id"] != doc and copy["version"] == 1
    assert copy["pinned"] is False and copy["archived"] is False
    ids = [e["id"] for e in client.get(f"/documents/{copy['id']}/scene").json()["elements"]]
    assert ids == ["a0", "a1", "a2"]
    assert copy["chunk_count"] == src["chunk_count"] and copy["open_offers"] == 0
    assert client.get(f"/documents/{copy['id']}/ops").json()["ops"] == []
    assert listing(client)[doc] == src
    assert client.post("/documents/nope/duplicate").status_code == 404
    monkeypatch.setattr(outline, "MAX_DOCUMENTS", 1)
    r = client.post(f"/documents/{doc}/duplicate")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many_canvases"


def test_migration_0007(tmp_path, monkeypatch):
    old = tmp_path / "m6"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("000[1-6]_*.sql")):
        shutil.copy(f, old / f.name)
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v6.db")
    assert db.migrate(conn) == [1, 2, 3, 4, 5, 6]
    db.ensure_default_document(conn)
    conn.execute(
        "UPDATE scenes SET version = 1, elements_json = ? WHERE document_id = 'default'",
        (json.dumps(ink_with_noise()),),
    )
    conn.commit()
    monkeypatch.undo()
    assert db.migrate(conn)[0] == 7  # later migrations apply too
    r = conn.execute("SELECT pinned, archived_at, last_opened_at FROM documents").fetchone()
    assert (r["pinned"], r["archived_at"], r["last_opened_at"]) == (0, None, None)
    # the stored count is backfilled: live elements only, no deleted ones and no drafts
    assert db.list_documents(conn)[0]["element_count"] == 3
    conn.close()


def test_list_reads_the_stored_count_not_the_scene_json(client):
    doc = new_canvas(client)
    version = save(client, doc, ink_with_noise())
    conn = db.connect()
    conn.execute("UPDATE scenes SET elements_json = 'not json' WHERE document_id = ?", (doc,))
    conn.commit()
    conn.close()
    assert listing(client)[doc]["element_count"] == 3  # json_each over the text would raise
    assert version == 1


def test_stored_count_follows_every_save_including_deltas(client):
    doc = new_canvas(client)
    els = ink_with_noise()
    save(client, doc, els)
    gone = {**els[0], "isDeleted": True, "version": 2}
    r = client.put(
        f"/documents/{doc}/scene", json={"base_version": 1, "elements": [gone], "delta": True}
    )
    assert r.status_code == 200
    assert listing(client)[doc]["element_count"] == 2
    rest = [
        {**e, "isDeleted": True, "version": 2} for e in els[1:]
    ]  # a save never deletes by omission
    r = client.put(f"/documents/{doc}/scene", json={"base_version": 2, "elements": rest})
    assert r.status_code == 200
    assert listing(client)[doc]["element_count"] == 0


def test_get_one_canvas_summary(client):
    doc = new_canvas(client, "Solo")
    save(client, doc, row("a", 2))
    r = client.get(f"/documents/{doc}")
    assert r.status_code == 200 and set(r.json()) == HOME_KEYS
    assert r.json()["title"] == "Solo" and r.json()["element_count"] == 2
    assert client.get("/documents/nope").status_code == 404


# --- thumbnails (Task 2) ---


def png_size(data):
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(data))
    return im.size, im


def sig_of(etag):
    """The chunk signature in a thumbnail ETag `"r<rev>v<version>c<sig>"`."""
    return etag.strip('"').split("c", 1)[1]


def test_thumbnail_png_and_cache(client, monkeypatch):
    from inkbridge import config
    from inkbridge.api import canvases
    from inkbridge.canvas import raster

    rev = raster.THUMB_REVISION
    doc = new_canvas(client)
    version = save(client, doc, row("a", 3))
    calls = []
    real = canvases.render_thumbnail
    monkeypatch.setattr(
        canvases, "render_thumbnail", lambda els, **kw: calls.append(1) or real(els, **kw)
    )
    r = client.get(f"/documents/{doc}/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert png_size(r.content)[0] == (960, 640)
    etag = r.headers["etag"]
    sig = sig_of(etag)
    assert etag == f'"r{rev}v{version}c{sig}"' and len(sig) == 8
    assert r.headers["cache-control"] == "no-cache"
    assert (config.thumbs_dir() / f"{doc}.r{rev}.{version}.{sig}.png").is_file()
    assert client.get(f"/documents/{doc}/thumbnail").status_code == 200
    assert len(calls) == 1
    cached = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b""
    assert len(calls) == 1


def test_thumbnail_follows_version(client):
    from inkbridge import config
    from inkbridge.canvas.raster import THUMB_REVISION as rev

    doc = new_canvas(client)
    v1 = save(client, doc, row("a", 3))
    s1 = sig_of(client.get(f"/documents/{doc}/thumbnail").headers["etag"])
    v2 = save(client, doc, row("a", 3) + row("b", 2, y=200), version=v1)
    s2 = sig_of(client.get(f"/documents/{doc}/thumbnail").headers["etag"])
    assert (config.thumbs_dir() / f"{doc}.r{rev}.{v2}.{s2}.png").is_file()
    assert not (config.thumbs_dir() / f"{doc}.r{rev}.{v1}.{s1}.png").exists()


def test_thumbnail_empty_and_draft_only_canvas(client):
    from inkbridge.canvas import raster

    empty = new_canvas(client)
    drafty = new_canvas(client)
    save(client, drafty, [{**row("d", 1)[0], "customData": {"draft": True}}])
    for doc in (empty, drafty):
        r = client.get(f"/documents/{doc}/thumbnail")
        assert r.status_code == 200
        size, im = png_size(r.content)
        assert size == (960, 640)
        assert [c for _, c in im.convert("RGB").getcolors()] == [raster.THUMB_BG]


def test_active_chunk_bounds_lists_active_auto_chunks_only(client):
    doc = new_canvas(client)
    v = save(client, doc, row("a", 3) + row("b", 3, x=2000))
    conn = db.connect()
    try:
        db.create_region(conn, doc, ["a0"], "manual.png")
        boxes = db.active_chunk_bounds(conn, doc)
        assert len(boxes) == 2
        assert all(set(b) == {"x", "y", "width", "height"} for b in boxes)
        assert sorted(b["x"] for b in boxes)[1] >= 2000 - 20
        save(
            client,
            doc,
            row("a", 3)
            + [{**e, "isDeleted": True, "version": e["version"] + 1} for e in row("b", 3, x=2000)],
            v,
        )
        assert len(db.active_chunk_bounds(conn, doc)) == 1
    finally:
        conn.close()


def test_thumbnail_shows_the_centre_chunk(client, monkeypatch):
    from inkbridge.api import canvases
    from inkbridge.canvas import raster

    doc = new_canvas(client)
    els = row("a", 3, x=0) + row("b", 3, x=2000) + row("c", 3, x=4000)
    save(client, doc, els)
    seen = {}
    real = canvases.render_thumbnail
    monkeypatch.setattr(
        canvases, "render_thumbnail", lambda e, **kw: seen.update(kw) or real(e, **kw)
    )
    png = client.get(f"/documents/{doc}/thumbnail").content
    conn = db.connect()
    try:
        assert seen["chunks"] == db.active_chunk_bounds(conn, doc) and len(seen["chunks"]) == 3
    finally:
        conn.close()
    assert png != raster.render_thumbnail(els)
    im = png_size(png)[1].convert("RGB")
    third = 960 // 3
    for x0 in (0, 2 * third):
        assert im.crop((x0, 0, x0 + third, 640)).getcolors(10) == [(third * 640, raster.THUMB_BG)]


def test_thumbnail_unknown_canvas_404(client):
    from inkbridge import config

    assert client.get("/documents/nope/thumbnail").status_code == 404
    assert client.get("/documents/..%2F..%2Fx/thumbnail").status_code == 404
    assert not config.thumbs_dir().exists() or not list(config.thumbs_dir().iterdir())


def test_thumbnail_304_asks_for_the_version_only(client, monkeypatch):
    from inkbridge.api import canvases
    from inkbridge.canvas.raster import THUMB_REVISION as rev

    doc = new_canvas(client)
    version = save(client, doc, row("a", 3))
    sig = sig_of(client.get(f"/documents/{doc}/thumbnail").headers["etag"])

    def boom(*a, **k):
        raise AssertionError("the 304 path must not load the scene")

    monkeypatch.setattr(canvases.db, "get_scene", boom)
    etag = f'"r{rev}v{version}c{sig}"'
    r = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": etag})
    assert r.status_code == 304
    assert (
        client.get(
            "/documents/nope/thumbnail", headers={"If-None-Match": f'"r{rev}v1"'}
        ).status_code
        == 404
    )


def test_thumbnail_serves_the_bytes_it_rendered(client, monkeypatch):
    from inkbridge.api import canvases

    doc = new_canvas(client)
    save(client, doc, row("a", 3))
    monkeypatch.setattr(canvases, "render_thumbnail", lambda els, **kw: b"rendered")
    monkeypatch.setattr(canvases, "_store", lambda *a, **k: None)  # nothing on disk to re-read
    r = client.get(f"/documents/{doc}/thumbnail")
    assert r.status_code == 200 and r.content == b"rendered"


def test_thumbnail_follows_a_manual_merge_without_a_scene_save(client):
    from inkbridge import config

    doc = new_canvas(client)
    version = save(client, doc, row("a", 3) + row("b", 3, y=200) + row("c", 3, y=900))
    first = client.get(f"/documents/{doc}/thumbnail")
    etag = first.headers["etag"]
    # nothing changed: the cached hit still answers 304
    again = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": etag})
    assert again.status_code == 304
    ids = [c["id"] for c in client.get(f"/documents/{doc}/regions", params={"chunks": True}).json()]
    assert len(ids) == 3
    merged = client.post(f"/documents/{doc}/chunks/merge", json={"chunk_ids": ids[:2]})
    assert merged.status_code == 200
    assert client.get(f"/documents/{doc}/scene").json()["version"] == version  # no scene save
    r = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag
    assert r.headers["etag"].startswith(f'"r3v{version}c')
    new_sig = sig_of(r.headers["etag"])
    assert [p.name for p in config.thumbs_dir().glob(f"{doc}.*")] == [
        f"{doc}.r3.{version}.{new_sig}.png"
    ]
    cached = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": r.headers["etag"]})
    assert cached.status_code == 304


def test_thumbnail_revision_replaces_old_cache(client, monkeypatch):
    from inkbridge import config
    from inkbridge.api import canvases
    from inkbridge.canvas import raster

    rev = raster.THUMB_REVISION
    doc = new_canvas(client)
    version = save(client, doc, row("a", 3))
    old = client.get(f"/documents/{doc}/thumbnail")
    sig = sig_of(old.headers["etag"])
    assert old.headers["etag"] == f'"r{rev}v{version}c{sig}"'
    monkeypatch.setattr(canvases, "THUMB_REVISION", rev + 1)
    r = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": old.headers["etag"]})
    assert r.status_code == 200 and r.headers["etag"] == f'"r{rev + 1}v{version}c{sig}"'
    assert (config.thumbs_dir() / f"{doc}.r{rev + 1}.{version}.{sig}.png").is_file()
    assert not (config.thumbs_dir() / f"{doc}.r{rev}.{version}.{sig}.png").exists()


def test_thumbnail_revision_two_cache_is_replaced_by_three(client):
    from inkbridge import config

    doc = new_canvas(client)
    version = save(client, doc, row("a", 3))
    config.thumbs_dir().mkdir(parents=True, exist_ok=True)
    old = config.thumbs_dir() / f"{doc}.r2.{version}.png"
    old.write_bytes(b"old")
    r = client.get(f"/documents/{doc}/thumbnail", headers={"If-None-Match": f'"r2v{version}"'})
    sig = sig_of(r.headers["etag"])
    assert r.status_code == 200 and r.headers["etag"] == f'"r3v{version}c{sig}"'
    assert not old.exists()
    assert (config.thumbs_dir() / f"{doc}.r3.{version}.{sig}.png").is_file()


def test_thumbnail_legacy_cache_file_is_ignored_and_removed(client):
    from inkbridge import config

    doc = new_canvas(client)
    version = save(client, doc, row("a", 3))
    config.thumbs_dir().mkdir(parents=True, exist_ok=True)
    legacy = config.thumbs_dir() / f"{doc}-{version}.png"
    other = config.thumbs_dir() / "other-3.png"
    legacy.write_bytes(b"old")
    other.write_bytes(b"keep")
    r = client.get(f"/documents/{doc}/thumbnail")
    assert r.status_code == 200 and png_size(r.content)[0] == (960, 640)
    assert not legacy.exists()
    assert other.read_bytes() == b"keep"


def test_thumbnail_cleanup_never_touches_a_canvas_whose_id_looks_like_a_revision(
    tmp_path, monkeypatch
):
    from inkbridge import config
    from inkbridge.api import canvases

    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "api.db"))

    d = config.thumbs_dir()
    d.mkdir(parents=True, exist_ok=True)
    mine = {
        "x.r1.4.png",
        "x.r2.3.png",
        "x.r3.4.deadbeef.png",
        "x-4.png",
    }  # older revisions and a legacy file of "x"
    theirs = {
        "x-r2.r2.3.png",
        "x-r2-3.png",
        "x-2-1.png",
        "y.r2.3.png",
        "x-r2.r3.3.deadbeef.png",
    }  # canvases "x-r2", "x-2", "y"
    for name in mine | theirs:
        (d / name).write_bytes(b"old")
    current = canvases._thumb_path("x", 5, "0badf00d")
    canvases._store(current, b"new", "x")
    assert current.read_bytes() == b"new"
    assert {p.name for p in d.iterdir()} == theirs | {current.name}
    other = canvases._thumb_path("x-r2", 7, "0badf00d")
    canvases._store(other, b"new", "x-r2")
    assert {p.name for p in d.iterdir()} == {"x-2-1.png", "y.r2.3.png", current.name, other.name}
