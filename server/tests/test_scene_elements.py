"""INK-110 (decision 0077): scenes are stored as one row per element."""

import json
import shutil
import sys
from pathlib import Path

from inkbridge import db

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

import make_real_scale


def dump(e):
    return json.dumps(e, ensure_ascii=False, separators=(",", ":"))


def old_database(tmp_path, monkeypatch, name="v7.db"):
    """A database at migration 0007 holding the real-scale fixture in the old blob column."""
    old = tmp_path / "migrations_v7"
    old.mkdir(exist_ok=True)
    for f in sorted(db.MIGRATIONS_DIR.glob("000[1-7]_*.sql")):
        shutil.copy(f, old / f.name)
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / name)
    assert db.migrate(conn) == [1, 2, 3, 4, 5, 6, 7]
    db.ensure_default_document(conn)
    els = make_real_scale.build()
    conn.execute(
        "UPDATE scenes SET version = 5, elements_json = ? WHERE document_id = 'default'",
        (dump(els),),
    )
    conn.commit()
    monkeypatch.undo()
    return conn, els


def test_migration_8_keeps_every_element_byte_identical(tmp_path, monkeypatch):
    conn, els = old_database(tmp_path, monkeypatch)
    assert any(e.get("pressures") and e.get("simulatePressure") is False for e in els)
    blob = conn.execute("SELECT elements_json FROM scenes").fetchone()[0]
    assert db.migrate(conn) == [8]
    rows = conn.execute("SELECT * FROM scene_elements ORDER BY pos").fetchall()
    assert len(rows) == len(els)
    assert [r["json"] for r in rows] == [dump(e) for e in els]
    for r, e in zip(rows, els, strict=True):
        assert r["seq"] == 5
        assert r["version"] == e["version"]
        assert r["is_deleted"] == int(bool(e.get("isDeleted")))
        if e["type"] == "freedraw":
            parsed = json.loads(r["json"])
            assert parsed["pressures"] == e["pressures"]
            assert parsed["simulatePressure"] == e["simulatePressure"]
    scene = conn.execute("SELECT version, elements_json FROM scenes").fetchone()
    assert (scene["version"], scene["elements_json"]) == (5, blob)
    conn.close()


def test_migration_8_runs_once(tmp_path, monkeypatch):
    conn, els = old_database(tmp_path, monkeypatch)
    assert db.migrate(conn) == [8]
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM scene_elements").fetchone()[0] == len(els)
    conn.execute("DELETE FROM scene_elements")
    conn.commit()
    conn.close()
    db.init_db(tmp_path / "v7.db")  # a normal start must not backfill again
    again = db.connect(tmp_path / "v7.db")
    assert again.execute("SELECT COUNT(*) FROM scene_elements").fetchone()[0] == 0
    again.close()


def test_migration_8_duplicate_ids_keep_the_last_at_the_first_position(tmp_path, monkeypatch):
    conn, _ = old_database(tmp_path, monkeypatch)
    a, b, a2 = {"id": "a", "v": 1}, {"id": "b"}, {"id": "a", "v": 2}
    conn.execute("UPDATE scenes SET elements_json = ?", (dump([a, b, a2]),))
    conn.commit()
    assert db.migrate(conn) == [8]
    rows = conn.execute("SELECT id, json FROM scene_elements ORDER BY pos").fetchall()
    assert [(r["id"], r["json"]) for r in rows] == [("a", dump(a2)), ("b", dump(b))]
    conn.close()


def test_fresh_database_has_the_table(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    assert db.migrate(conn) == [1, 2, 3, 4, 5, 6, 7, 8]
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(scene_elements)")}
    assert cols == {"document_id", "id", "pos", "seq", "version", "nonce", "is_deleted", "json", "updated_at"}
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(scene_elements)")}
    assert "scene_elements_seq" in indexes
    info = conn.execute("PRAGMA index_info(scene_elements_seq)").fetchall()
    assert [r["name"] for r in info] == ["document_id", "seq"]
    conn.close()
