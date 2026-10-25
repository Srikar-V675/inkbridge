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
        "content_hash",
        "successor_of",
        "png_stale",
        "png_path",
        "status",
        "updated_at",
    },
    "recognitions": {
        "region_id",
        "content_hash",
        "source",
        "model",
        "text",
        "latex",
        "text_hash",
        "created_at",
    },
    "agent_ops": {
        "id",
        "type",
        "payload_json",
        "status",
        "document_id",
        "created_at",
        "result_json",
        "error",
    },
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
    files = sorted(db.MIGRATIONS_DIR.glob("*.sql"))
    assert db.migrate(conn) == list(range(1, len(files) + 1))
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


def test_second_migrator_waits_for_the_first_then_applies_nothing(tmp_path, monkeypatch):
    """Two processes starting on one database: the second must not apply migrations in parallel."""
    import threading

    path = tmp_path / "t.db"
    pre = db.connect(path)  # an existing database: creating schema_version takes no write lock
    pre.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    pre.commit()
    pre.close()
    started, release = threading.Event(), threading.Event()
    real_apply = db._apply_migration

    def paused_apply(conn, version, sql):
        if threading.current_thread().name == "a" and version == 1:
            started.set()
            assert release.wait(10)
        real_apply(conn, version, sql)

    monkeypatch.setattr(db, "_apply_migration", paused_apply)
    results: dict[str, object] = {}

    def run(name):
        c = db.connect(path)
        try:
            results[name] = db.migrate(c)  # an exception leaves no result: the asserts catch it
        finally:
            c.close()

    a = threading.Thread(target=run, args=("a",), name="a")
    a.start()
    assert started.wait(10)
    b = threading.Thread(target=run, args=("b",), name="b")
    b.start()
    b.join(0.5)
    assert b.is_alive(), "second migrator did not wait for the first"
    release.set()
    a.join(10)
    b.join(10)
    files = sorted(db.MIGRATIONS_DIR.glob("*.sql"))
    assert results["a"] == list(range(1, len(files) + 1))
    assert results["b"] == []


def test_failed_migration_leaves_nothing_applied(tmp_path, monkeypatch):
    import shutil

    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(next(db.MIGRATIONS_DIR.glob("0001_*.sql")), mig)
    (mig / "0002_broken.sql").write_text("CREATE TABLE ok_so_far (x);\nNOT VALID SQL;\n")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", mig)
    c = db.connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(c)
    tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "documents" not in tables and "ok_so_far" not in tables
    (mig / "0002_broken.sql").write_text("-- fixed; a comment with ; inside\nCREATE TABLE ok (x);")
    assert db.migrate(c) == [1, 2]
    c.close()


def test_migrate_splits_statements_like_executescript(tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_x.sql").write_text(
        "CREATE TABLE t (s TEXT); INSERT INTO t VALUES ('a;b');\n"
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN\n  INSERT INTO t2 VALUES (1);\nEND;\n"
        "CREATE TABLE t2 (n); -- trailing comment\n"
    )
    monkeypatch.setattr(db, "MIGRATIONS_DIR", mig)
    c = db.connect(tmp_path / "t.db")
    assert db.migrate(c) == [1]
    assert [r["s"] for r in c.execute("SELECT s FROM t")] == ["a;b"]
    c.execute("INSERT INTO t VALUES ('c')")
    assert c.execute("SELECT count(*) FROM t2").fetchone()[0] == 1
    c.close()
