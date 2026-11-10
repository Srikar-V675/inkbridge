"""INK-122: migration 0009, v2 persistence, readers and the recognizer skip."""

import json
import shutil
import sqlite3

import pytest

from inkbridge import db
from inkbridge.db.outline import chunk_outline
from tests.test_chunk_persistence import Canvas
from tests.test_chunker import arrow
from tests.test_chunker_v2 import hub_and_spoke, native, vee, words
from tests.test_strokes import line, word


def conn_rows(sql, *args):
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def stroke_links():
    return conn_rows("SELECT * FROM links ORDER BY from_region, to_region, element_id")


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v2")


def cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_9_rebuilds_links_and_keeps_rows(tmp_path, monkeypatch):
    old = tmp_path / "migrations_v8"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("000[1-8]_*.sql")):
        shutil.copy(f, old / f.name)
    real = db.migrations.MIGRATIONS_DIR
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v8.db")
    assert db.migrate(conn) == list(range(1, 9))
    db.ensure_default_document(conn)
    for rid in ("r1", "r2"):
        conn.execute(
            "INSERT INTO regions (id, document_id, element_ids_json, bbox, kind, created_by,"
            " status, updated_at) VALUES (?, 'default', '[]', '{}', 'handwriting', 'auto',"
            " 'active', 't')",
            (rid,),
        )
    conn.execute("INSERT INTO links VALUES ('default', 'r1', 'r2', 'arrow')")
    conn.commit()
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", real)
    assert 9 in db.migrate(conn)
    row = conn.execute("SELECT * FROM links").fetchone()
    assert (row["source"], row["element_id"], row["label"], row["confidence"]) == (
        "stroke",
        "",
        None,
        None,
    )
    ins = "INSERT INTO links (document_id, from_region, to_region, kind, source, element_id)"
    conn.execute(f"{ins} VALUES ('default', 'r1', 'r2', 'relates', 'agent', '')")
    conn.execute(f"{ins} VALUES ('default', 'r1', 'r2', 'arrow', 'stroke', 'x')")
    for kind, source in (("bogus", "stroke"), ("arrow", "bogus")):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"{ins} VALUES ('default', 'r1', 'r2', '{kind}', '{source}', '')")
    assert cols(conn, "links") == {
        "document_id",
        "from_region",
        "to_region",
        "kind",
        "source",
        "label",
        "confidence",
        "element_id",
    }
    assert "chunker" in cols(conn, "documents")
    conn.execute("UPDATE documents SET chunker = 'v2'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE documents SET chunker = 'v3'")
    conn.close()


def test_v2_save_writes_stroke_link_rows(client, v2):
    canvas = Canvas(client, hub_and_spoke())
    rows = stroke_links()
    assert len(rows) == 5
    assert {r["element_id"] for r in rows} == {"cr", "cl", "cu", "cd", "na"}
    assert {r["source"] for r in rows} == {"stroke"} and {r["kind"] for r in rows} == {"arrow"}
    assert all(0 <= r["confidence"] <= 1 for r in rows)
    members = {i for c in canvas.chunks("active") for i in c["element_ids"]}
    assert not members & {"cr", "cl", "cu", "cd", "na", "na-label", "cr-head"}


def test_non_stroke_links_survive_a_save_and_stroke_links_are_rebuilt(client, v2):
    canvas = Canvas(client, hub_and_spoke())
    a, b = canvas.chunk_of("h0")["id"], canvas.chunk_of("r0")["id"]
    conn = db.connect()
    conn.execute(
        "INSERT INTO links (document_id, from_region, to_region, kind, source)"
        " VALUES ('default', ?, ?, 'relates', 'agent')",
        (a, b),
    )
    conn.commit()
    conn.close()
    for i in ("cr", "cr-head", "cl", "cl-head", "cu", "cu-head", "cd", "cd-head", "na"):
        canvas.el(i)["isDeleted"] = True
    canvas.put()
    rows = stroke_links()
    assert [(r["source"], r["kind"]) for r in rows] == [("agent", "relates")]


def test_orphaned_chunk_drops_its_links_via_gc(client, v2, monkeypatch):
    canvas = Canvas(client, hub_and_spoke())
    a, b = canvas.chunk_of("h0")["id"], canvas.chunk_of("r0")["id"]
    conn = db.connect()
    conn.execute(
        "INSERT INTO links (document_id, from_region, to_region, kind, source)"
        " VALUES ('default', ?, ?, 'relates', 'agent')",
        (a, b),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db.chunks, "ORPHAN_KEEP", 0)
    for i in ("r0", "r1", "r2"):
        canvas.el(i)["isDeleted"] = True
    canvas.put()
    assert conn_rows("SELECT * FROM links WHERE source = 'agent'") == []


def test_moving_an_arrow_changes_no_chunk_hash_through_the_api(client, v2):
    canvas = Canvas(client, hub_and_spoke())

    def state():
        return {
            c["id"]: (c["content_hash"], c["png_stale"], c["updated_at"])
            for c in canvas.chunks("active")
        }

    conn = db.connect()
    conn.execute("UPDATE regions SET png_stale = 0")
    conn.commit()
    conn.close()
    before = {
        c["id"]: (c["content_hash"], c["stroke_hash"], c["png_stale"], c["updated_at"])
        for c in conn_rows_regions()
    }
    pairs = {(r["from_region"], r["to_region"], r["element_id"]) for r in stroke_links()}
    for i in ("cr", "cr-head"):
        canvas.el(i)["x"] += 5
        canvas.el(i)["y"] += 5
    canvas.put()
    after = {
        c["id"]: (c["content_hash"], c["stroke_hash"], c["png_stale"], c["updated_at"])
        for c in conn_rows_regions()
    }
    assert after == before
    assert {(r["from_region"], r["to_region"], r["element_id"]) for r in stroke_links()} == pairs
    assert state()


def conn_rows_regions():
    return conn_rows("SELECT * FROM regions WHERE status = 'active'")


def test_connector_chunk_is_never_a_recognition_candidate(client, v2):
    hub = words("h", 0, 0)
    canvas = Canvas(
        client,
        [*hub, line("c", 85, 8, 285, 8, index="a0"), vee("c-head", 275, 8, index="a1")],
    )
    kinds = {c["element_ids"][0]: c["kind"] for c in canvas.chunks("active")}
    assert kinds["c"] == "connector"
    conn = db.connect()
    try:
        cands = db.recognition_candidates(conn, "default", include_stale=True)
    finally:
        conn.close()
    assert [json.loads(c["element_ids_json"])[0] for c in cands] == ["h0"]
    from inkbridge.db.sync import needs_reading

    def region(c):
        return {"id": c["id"], "content_hash": "new", "source": None, "png_stale": 0,
                "kind": c["kind"], "bounds": {"width": 100, "height": 10}, "stroke_count": 3}  # fmt: skip

    chunks = {c["element_ids"][0]: c for c in canvas.chunks("active")}
    resolved = [
        ({"hash": "old"}, region(chunks["c"]), None),
        ({"hash": "old"}, region(chunks["h0"]), None),
    ]
    assert needs_reading(resolved) == [chunks["h0"]["id"]]


def test_v1_save_writes_the_same_links_as_before(client):
    from tests.test_links import nodes

    canvas = Canvas(client, [*nodes(), arrow("arr", 100, 50, 1900, start="a", end="b")])
    (row,) = stroke_links()
    assert (row["kind"], row["source"], row["element_id"]) == ("arrow", "stroke", "")
    assert row["from_region"] == canvas.chunk_of("a")["id"]


def test_readers_dedupe_parallel_arrows(client, v2):
    hub = words("h", 0, 0)
    far = words("f", 500, 0)
    na = native("n1", "arrow", 85, 4)
    na["points"] = [[0, 0], [410, 0]]
    nb = native("n2", "arrow", 85, 12)
    nb["points"] = [[0, 0], [410, 0]]
    canvas = Canvas(client, [*hub, *far, na, nb])
    assert len(stroke_links()) == 2
    conn = db.connect()
    try:
        assert len(db.list_links(conn, "default")) == 1
        outline = chunk_outline(conn, "default")["chunks"]
    finally:
        conn.close()
    sources = [c for c in outline if c["links"]]
    assert len(sources) == 1 and len(sources[0]["links"]) == 1
    assert canvas.chunk_of("h0")


# --- switching the chunker per canvas ---


def two_line_hub():
    """Two lines of words 150 px apart joined by a pen arrow (v1 glues all of it into one chunk,
    v2 keeps the arrow out and the two lines apart), and an untouched cluster far away."""
    return [
        *words("a", 0, 0),
        *words("b", 0, 150),
        line("c", 30, 18, 30, 140, index="a0"),
        vee("c-head", 20, 140, index="a1"),
        *words("f", 3000, 0),
    ]


def set_chunker(version):
    conn = db.connect()
    try:
        db.set_chunker(conn, "default", version)
    finally:
        conn.close()


def active_regions():
    return {
        tuple(json.loads(r["element_ids_json"])): r
        for r in conn_rows("SELECT * FROM regions WHERE status = 'active'")
    }


def test_set_chunker_rechunks_now_and_keeps_ids_where_ink_matches(client):
    canvas = Canvas(client, two_line_hub())
    before = active_regions()
    hub = canvas.chunk_of("a0")
    far = canvas.chunk_of("f0")
    assert "c" in hub["element_ids"] and "b0" in hub["element_ids"]  # v1: one chunk, arrow inside
    set_chunker("v2")
    after = active_regions()
    assert {k for k in after} >= {("a0", "a1", "a2"), ("b0", "b1", "b2"), ("f0", "f1", "f2")}
    assert not any("c" in k or "c-head" in k for k in after if k[0] != "c")
    kept = after[("f0", "f1", "f2")]
    assert kept["id"] == far["id"] and kept["content_hash"] == far["content_hash"]
    assert before[tuple(hub["element_ids"])]["id"] == hub["id"]
    old = canvas_region(hub["id"])
    assert old["status"] == "orphaned" and old["successor_of"] in {r["id"] for r in after.values()}
    set_chunker("v1")
    assert len([k for k in active_regions() if "a0" in k]) == 1
    assert [
        r["chunker"] for r in conn_rows("SELECT chunker FROM documents WHERE id='default'")
    ] == ["v1"]
    set_chunker(None)
    assert conn_rows("SELECT chunker FROM documents WHERE id='default'")[0]["chunker"] is None


def canvas_region(rid):
    return conn_rows("SELECT * FROM regions WHERE id = ?", rid)[0]


def note_of(chunk):
    return {"id": chunk["id"], "hash": chunk["content_hash"], "reading": chunk["text_hash"]}


def read_all(canvas, text="words"):
    from tests.test_search import recognise

    for c in canvas.chunks("active"):
        recognise(c, f"{text} {c['element_ids'][0]}")


def test_check_sync_reports_replaced_after_switching_to_v2(client):
    canvas = Canvas(client, two_line_hub())
    read_all(canvas)
    hub, far = canvas.chunk_of("a0"), canvas.chunk_of("f0")
    notes = [note_of(hub), note_of(far)]
    assert client.patch("/documents/default", json={"chunker": "v2"}).status_code == 200
    read_all(canvas)
    r = client.post("/documents/default/check_sync", json={"chunks": notes}).json()
    live = {c["id"] for c in canvas.chunks("active")}
    assert [x["id"] for x in r["replaced"]] == [hub["id"]]
    assert r["replaced"][0]["successor"] in live
    assert r["fresh"] == [far["id"]] and r["removed"] == []


def test_check_sync_reports_both_old_ids_replaced_when_v2_merges(client):
    small = [
        {
            "id": f"r{k}",
            "type": "rectangle",
            "x": 20000 + 100 * k,
            "y": 3000,
            "width": 4,
            "height": 4,
        }
        for k in range(30)
    ]
    spare = [word(f"s{k}", 8000 + 200 * k, 3000) for k in range(3)]
    canvas = Canvas(client, [word("a", 0, 0), word("b", 45, 0), *spare, *small])
    read_all(canvas)
    a, b = canvas.chunk_of("a"), canvas.chunk_of("b")
    assert a["id"] != b["id"]  # v1: the many tiny shapes make the page median 4 px
    client.patch("/documents/default", json={"chunker": "v2"})
    read_all(canvas)
    r = client.post(
        "/documents/default/check_sync", json={"chunks": [note_of(a), note_of(b)]}
    ).json()
    merged = canvas.chunk_of("a")
    assert [(x["id"], x["successor"]) for x in r["replaced"]] == [
        (a["id"], merged["id"]),
        (b["id"], merged["id"]),
    ]
    assert merged["id"] not in [n["id"] for n in r["new"]] and r["removed"] == []


def test_patch_documents_chunker(client, monkeypatch):
    monkeypatch.delenv("INKBRIDGE_CHUNKER", raising=False)
    Canvas(client, two_line_hub())
    r = client.patch("/documents/default", json={"chunker": "v2"})
    assert r.status_code == 200 and r.json()["chunker"] == "v2"
    assert client.get("/documents/default").json()["chunker"] == "v2"
    assert [d["chunker"] for d in client.get("/documents").json() if d["id"] == "default"] == ["v2"]
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v2")
    r = client.patch("/documents/default", json={"chunker": "default"})
    assert r.json()["chunker"] == "v2"  # follows the env now
    monkeypatch.delenv("INKBRIDGE_CHUNKER")
    assert client.get("/documents/default").json()["chunker"] == "v1"
    assert client.patch("/documents/default", json={"chunker": "v3"}).status_code == 422
    assert client.patch("/documents/default", json={}).status_code == 422
    assert client.patch("/documents/nope", json={"chunker": "v2"}).status_code == 404
    other = client.post("/documents", json={"title": "Old"}).json()["id"]
    assert client.patch(f"/documents/{other}", json={"archived": True}).status_code == 200
    r = client.patch(f"/documents/{other}", json={"chunker": "v2"})
    assert r.status_code == 200 and r.json()["archived"] is True and r.json()["chunker"] == "v2"


def test_env_selects_v2_for_canvases_without_override(client, v2):
    canvas = Canvas(client, hub_and_spoke())
    members = {i for c in canvas.chunks("active") for i in c["element_ids"]}
    assert "cr" not in members and "na" not in members


def test_override_beats_env(client, monkeypatch):
    client.patch("/documents/default", json={"chunker": "v1"})
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v2")
    canvas = Canvas(client, hub_and_spoke())
    members = {i for c in canvas.chunks("active") for i in c["element_ids"]}
    assert "cr" in members  # v1 keeps pen connectors in chunks


def test_set_chunker_unknown_canvas_raises_document_not_found(client):
    conn = db.connect()
    try:
        with pytest.raises(db.DocumentNotFound):
            db.set_chunker(conn, "nope", "v2")
        with pytest.raises(ValueError):
            db.set_chunker(conn, "default", "v3")
    finally:
        conn.close()


def test_set_chunker_is_one_transaction(client, monkeypatch):
    Canvas(client, two_line_hub())

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(db.chunks, "_sync_chunks", boom)
    with pytest.raises(RuntimeError):
        set_chunker("v2")
    assert conn_rows("SELECT chunker FROM documents WHERE id = 'default'")[0]["chunker"] is None
