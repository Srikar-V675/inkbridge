"""Migration 0011 (INK-114): draft elements leave scene_elements."""

import json
import shutil

from inkbridge import db


def dump(e):
    return json.dumps(e, ensure_ascii=False, separators=(",", ":"))


def el(eid, draft=False, op=None, **extra):
    cd = {"author": "agent", "draft": True, **({"op_id": op} if op else {})} if draft else None
    return {
        "id": eid,
        "type": "text",
        "x": 0,
        "y": 0,
        "width": 50,
        "height": 20,
        "version": 3,
        "versionNonce": 7,
        "isDeleted": False,
        **({"customData": cd} if cd else {}),
        **extra,
    }


def test_migration_11_moves_drafts_out_of_the_scene(tmp_path, monkeypatch):
    old = tmp_path / "migrations_v10"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(f.name.split("_")[0]) <= 10:
            shutil.copy(f, old / f.name)
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v10.db")
    assert db.migrate(conn) == list(range(1, 11))
    db.ensure_default_document(conn)
    monkeypatch.undo()

    user = {**el("user-1"), "type": "freedraw", "points": [[0, 0], [5, 5]], "pressures": [0.3, 0.6]}
    rows = [user, el("acc:1", True, "acc"), el("app:1", True, "app"), el("app:2", True, "app"),
            el("rej:1", True, "rej"), el("lonely", True)]
    for pos, e in enumerate(rows):
        conn.execute(
            "INSERT INTO scene_elements (document_id, id, pos, seq, version, nonce, is_deleted, json,"
            " updated_at) VALUES ('default', ?, ?, 1, 3, 7, 0, ?, 'now')",
            (e["id"], pos, dump(e)),
        )
    for op, status in (("acc", "accepted"), ("app", "applied"), ("rej", "rejected"), ("stuck", "applied")):
        conn.execute(
            "INSERT INTO agent_ops (id, document_id, type, payload_json, status, created_at)"
            " VALUES (?, 'default', 'write_text', '{}', ?, 'now')",
            (op, status),
        )
    conn.execute("UPDATE scenes SET version = 4")
    conn.commit()
    before = conn.execute("SELECT json FROM scene_elements WHERE id = 'user-1'").fetchone()[0]

    assert db.migrate(conn)[:4] == [11, 12, 13, 14]  # later migrations also apply (INK-133)
    got = {r["id"]: json.loads(r["json"]) for r in conn.execute("SELECT id, json FROM scene_elements")}
    assert conn.execute("SELECT json FROM scene_elements WHERE id = 'user-1'").fetchone()[0] == before
    assert "draft" not in got["acc:1"]["customData"] and got["acc:1"]["version"] == 4
    assert not got["acc:1"]["isDeleted"]
    assert got["app:1"]["isDeleted"] and got["app:2"]["isDeleted"] and got["app:1"]["version"] == 4
    assert got["rej:1"]["isDeleted"] and got["lonely"]["isDeleted"]
    ops = {r["id"]: r for r in conn.execute("SELECT * FROM agent_ops")}
    assert ops["app"]["status"] == "placed" and ops["stuck"]["status"] == "expired"
    placed = json.loads(ops["app"]["elements_json"])
    assert [e["id"] for e in placed] == ["app:1", "app:2"]
    assert all(e["customData"]["draft"] for e in placed) and json.loads(ops["app"]["box_json"])
    assert conn.execute("SELECT version FROM scenes").fetchone()[0] == 5
    assert conn.execute("SELECT element_count FROM scenes").fetchone()[0] == 2  # user-1, acc:1
    chunk_ids = [json.loads(r[0]) for r in conn.execute(
        "SELECT element_ids_json FROM regions WHERE created_by = 'auto' AND status = 'active'")]
    assert ["acc:1"] in chunk_ids
    seqs = {r["id"]: r["seq"] for r in conn.execute("SELECT id, seq FROM scene_elements")}
    assert seqs["acc:1"] == seqs["rej:1"] == seqs["app:1"] == 5 and seqs["user-1"] == 1
    snapshot = [tuple(r) for r in conn.execute("SELECT * FROM scene_elements ORDER BY id")]
    assert db.migrate(conn) == []
    assert [tuple(r) for r in conn.execute("SELECT * FROM scene_elements ORDER BY id")] == snapshot
    conn.close()
