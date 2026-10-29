import json
import shutil

from inkbridge import db
from inkbridge.regions import content_hash, stroke_hash
from tests.test_regions_api import SCENE, A, B, post
from tests.test_search import recognise, search


def cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v2_tables_and_columns(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    assert {"successor_of", "content_hash"} <= cols(conn, "regions")
    assert cols(conn, "recognitions") == {
        "region_id",
        "content_hash",
        "source",
        "model",
        "text",
        "latex",
        "text_hash",
        "created_at",
    }
    assert cols(conn, "links") == {"document_id", "from_region", "to_region", "kind"}
    assert cols(conn, "questions") == {
        "id",
        "document_id",
        "parent_id",
        "text",
        "focus_element_ids",
        "answer_md",
        "sources_json",
        "status",
        "runner_ref",
        "created_at",
    }
    assert {"document_id", "created_at", "result_json", "error"} <= cols(conn, "agent_ops")
    conn.close()


def test_moving_a_region_keeps_its_reading_but_makes_the_crop_stale(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    recognise(ra, "hello world")
    assert ra["content_hash"] == content_hash([A])
    moved = {**A, "x": A["x"] + 300, "y": A["y"] + 50}
    client.put(SCENE, json={"base_version": 1, "elements": [moved, B]})
    after = client.get(f"/regions/{ra['id']}").json()
    assert after["stroke_hash"] != ra["stroke_hash"] and after["stroke_hash"] == stroke_hash(
        [moved]
    )
    assert after["png_stale"] is True
    assert after["content_hash"] == ra["content_hash"]
    assert after["text"] == "hello world"
    assert [h["region_id"] for h in search(client, "hello")] == [ra["id"]]


def test_text_hash_is_stored_with_the_reading(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    recognise(ra, "hello  world")
    assert client.get(f"/regions/{ra['id']}").json()["text_hash"] == db.text_hash(
        "hello world", None
    )


def test_changing_a_point_drops_the_old_reading(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    recognise(ra, "hello world")
    client.put(SCENE, json={"base_version": 1, "elements": [{**A, "points": [[0, 0], [5, 5]]}, B]})
    after = client.get(f"/regions/{ra['id']}").json()
    assert after["text"] is None and after["content_hash"] != ra["content_hash"]
    assert search(client, "hello") == []


def test_migration_applies_on_a_v1_database_without_losing_readings(tmp_path, monkeypatch):
    old = tmp_path / "migrations_v1"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("000[123]_*.sql")):
        shutil.copy(f, old / f.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v1.db")
    assert db.migrate(conn) == [1, 2, 3]
    db.ensure_default_document(conn)
    elements = [A, B]
    conn.execute(
        "UPDATE scenes SET version = 1, elements_json = ? WHERE document_id = 'default'",
        (json.dumps(elements),),
    )
    live_hash = stroke_hash([A])
    conn.execute(
        "INSERT INTO regions (id, document_id, element_ids_json, bbox, created_by, stroke_hash,"
        " png_path, status, updated_at) VALUES ('r1','default','[\"a\"]','{}','user',?,'p','active','t')",
        (live_hash,),
    )
    conn.execute(
        "INSERT INTO recognitions (region_id, stroke_hash, source, text, created_at)"
        " VALUES ('r1', ?, 'gemini', 'kept reading', 't')",
        (live_hash,),
    )
    # A reading from before the ink was moved: same source, old key. It must neither collide with
    # the re-keyed current reading nor be selected, and a stale index row must be rebuilt.
    conn.execute(
        "INSERT INTO recognitions (region_id, stroke_hash, source, text, created_at)"
        " VALUES ('r1', ?, 'gemini', 'stale reading', 't')",
        (stroke_hash([{**A, "x": A["x"] - 300}]),),
    )
    conn.execute(
        "INSERT INTO region_fts (region_id, document_id, text, latex)"
        " VALUES ('r1', 'default', 'stale reading', NULL)"
    )
    conn.commit()
    monkeypatch.undo()  # back to the real migrations directory
    assert db.migrate(conn) == [4, 5]
    region = db.get_region(conn, "r1")
    assert region["content_hash"] == content_hash([A])
    assert region["text"] == "kept reading"
    assert region["text_hash"] == db.text_hash("kept reading", None)
    indexed = [r["text"] for r in conn.execute("SELECT text FROM region_fts WHERE region_id='r1'")]
    assert indexed == ["kept reading"]
    conn.close()


def test_backfill_reruns_if_a_previous_run_was_interrupted(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    db.ensure_default_document(conn)
    conn.execute(
        "UPDATE scenes SET version = 1, elements_json = ? WHERE document_id = 'default'",
        (json.dumps([A]),),
    )
    conn.execute(
        "INSERT INTO regions (id, document_id, element_ids_json, bbox, created_by, stroke_hash,"
        " png_path, status, updated_at) VALUES ('r1','default','[\"a\"]','{}','user',?,'p','active','t')",
        (stroke_hash([A]),),
    )  # content_hash left NULL, as after a crash between schema_version and the backfill
    conn.execute(  # copied by 0004 with its old stroke-hash key, not yet re-keyed
        "INSERT INTO recognitions (region_id, content_hash, source, text, created_at)"
        " VALUES ('r1', ?, 'gemini', 'kept reading', 't')",
        (stroke_hash([A]),),
    )
    conn.commit()
    db.init_db(tmp_path / "t.db")  # the normal start-up path
    c2 = db.connect(tmp_path / "t.db")
    healed = db.get_region(c2, "r1")
    assert healed["content_hash"] == content_hash([A])
    assert healed["text"] == "kept reading"
    c2.close()
    conn.close()
