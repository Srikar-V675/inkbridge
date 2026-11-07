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


# --- saving rows (Task 2) ---------------------------------------------------------------------

from datetime import UTC, datetime, timedelta

from tests.test_ops_api import OPS, write

SCENE = "/documents/default/scene"


def el(eid, v=1, **extra):
    return {
        "id": eid,
        "type": "freedraw",
        "x": 0,
        "y": 0,
        "version": v,
        "versionNonce": v,
        "points": [[0, 0], [5, 5]],
        "pressures": [0.5, 0.7],
        "simulatePressure": False,
        **extra,
    }


def head(client):
    return client.get(SCENE).json()["version"]


def put(client, elements, delta=False):
    r = client.put(SCENE, json={"base_version": head(client), "elements": elements, "delta": delta})
    assert r.status_code == 200, r.text
    return r.json()["version"]


def rows(order="pos"):
    conn = db.connect()
    try:
        return conn.execute(f"SELECT * FROM scene_elements ORDER BY {order}").fetchall()
    finally:
        conn.close()


def later(days):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def test_save_writes_only_changed_rows(client):
    first = put(client, [el("a"), el("b"), el("c")])
    assert {r["seq"] for r in rows()} == {first}
    second = put(client, [el("b", 2, x=9), el("d")], delta=True)
    by_id = {r["id"]: r for r in rows()}
    assert (by_id["a"]["seq"], by_id["c"]["seq"]) == (first, first)
    assert (by_id["b"]["seq"], by_id["d"]["seq"]) == (second, second)
    assert by_id["b"]["version"] == 2
    assert [r["id"] for r in rows()] == ["a", "b", "c", "d"]  # slots kept, new id appended
    assert head(client) == second


def test_row_json_keeps_pressures_and_float_spelling(client):
    put(client, [el("a", pressures=[0.5, 0.7], points=[[0, 0], [1.25, 3]])])
    stored = json.loads(rows()[0]["json"])
    assert stored["pressures"] == [0.5, 0.7] and stored["simulatePressure"] is False
    assert stored["points"] == [[0, 0], [1.25, 3]]


def test_deleted_element_becomes_a_deleted_row_with_full_json(client):
    put(client, [el("a")])
    put(client, [el("a", 2, isDeleted=True)], delta=True)
    r = rows()[0]
    assert r["is_deleted"] == 1 and json.loads(r["json"])["points"] == [[0, 0], [5, 5]]


def test_full_put_drops_omitted_rows(client):
    put(client, [el("a"), el("b")])
    put(client, [el("a")])
    assert [r["id"] for r in rows()] == ["a"]


def test_undo_of_a_deleted_element_revives_the_row(client):
    put(client, [el("a"), el("b")])
    put(client, [el("a", 2, isDeleted=True)], delta=True)
    pos = {r["id"]: r["pos"] for r in rows()}
    put(client, [el("a", 3)], delta=True)
    again = {r["id"]: r for r in rows()}["a"]
    assert again["is_deleted"] == 0 and again["pos"] == pos["a"] and again["version"] == 3


def shrink(days=15):
    conn = db.connect()
    try:
        n = db.shrink_tombstones(conn, "default", now=later(days))
        conn.commit()
        return n
    finally:
        conn.close()


def test_tombstones_shrink_after_14_days(client):
    put(client, [el("a"), el("b")])
    seq = put(client, [el("a", 2, isDeleted=True)], delta=True)
    assert shrink(13) == 0
    assert "points" in rows()[0]["json"]
    assert shrink(15) == 1
    a, b = rows()
    assert json.loads(a["json"]) == {"id": "a", "version": 2, "versionNonce": 2, "isDeleted": True}
    assert (a["seq"], a["version"], a["is_deleted"]) == (seq, 2, 1)
    assert "points" in b["json"]  # a live row is untouched
    conn = db.connect()
    assert [e["id"] for e in json.loads(db.get_scene(conn, "default")[1])] == ["b"]
    stubbed = json.loads(db.get_scene(conn, "default", stubs=True)[1])
    assert [e["id"] for e in stubbed] == ["a", "b"]
    conn.close()
    put(client, [el("a", 3)], delta=True)  # undo after the shrink restores a full row
    assert "points" in {r["id"]: r for r in rows()}["a"]["json"]


def test_op_payload_naming_a_tombstoned_id_is_refused(client):
    put(client, [el("gone"), el("kept")])
    put(client, [el("gone", 2, isDeleted=True)], delta=True)
    assert shrink(15) == 1
    r = write(client, text="gone")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "existing_element_id"
    assert client.get(OPS).json()["ops"] == []
