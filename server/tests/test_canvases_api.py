"""INK-118: canvases home (summaries, patch, open, duplicate) and the thumbnail cache."""

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
    monkeypatch.undo()
    assert db.migrate(conn) == [7]
    r = conn.execute("SELECT pinned, archived_at, last_opened_at FROM documents").fetchone()
    assert (r["pinned"], r["archived_at"], r["last_opened_at"]) == (0, None, None)
    conn.close()
