import sqlite3

import pytest

from inkbridge import config, db

EXPECTED = {
    "documents": {"id", "title", "updated_at"},
    "scenes": {"document_id", "version", "elements_json", "updated_at"},
    "regions": {
        "id",
        "document_id",
        "element_ids_json",
        "bbox",
        "kind",
        "created_by",
        "stroke_hash",
        "png_path",
        "status",
        "updated_at",
    },
    "recognitions": {
        "region_id",
        "stroke_hash",
        "source",
        "model",
        "text",
        "latex",
        "created_at",
    },
    "agent_ops": {"id", "type", "payload_json", "status"},
}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_migrate_creates_all_tables_and_columns(conn):
    db.migrate(conn)
    for table, cols in EXPECTED.items():
        assert columns(conn, table) == cols, table


def test_migrate_twice_is_noop(conn):
    assert db.migrate(conn) == [1]
    assert db.migrate(conn) == []


def test_init_db_creates_default_document_and_scene_once(tmp_path):
    path = tmp_path / "nested" / "t.db"
    db.init_db(path)
    db.init_db(path)
    c = db.connect(path)
    docs = c.execute("SELECT id FROM documents").fetchall()
    scene = c.execute("SELECT version, elements_json FROM scenes").fetchall()
    c.close()
    assert [d["id"] for d in docs] == [db.DEFAULT_DOCUMENT_ID]
    assert [(s["version"], s["elements_json"]) for s in scene] == [(0, "[]")]


def test_foreign_keys_enforced(conn):
    db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO regions (id, document_id) VALUES ('r1', 'missing')")


def test_db_path_reads_env_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "x.db"))
    assert config.db_path() == tmp_path / "x.db"
    monkeypatch.delenv("INKBRIDGE_DB")
    assert config.db_path() == config.DATA_DIR / "inkbridge.db"
