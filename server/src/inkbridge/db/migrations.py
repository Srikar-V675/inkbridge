"""Schema migrations and database setup (decision 0010 migration lock)."""

import json
import logging
import random
import re
import sqlite3
from pathlib import Path

from inkbridge.canvas.hashes import (
    bbox_of,
    content_hash,
    legacy_content_hash,
    text_hash,
)

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import _now, connect
from inkbridge.db.documents import ensure_default_document
from inkbridge.db.elements import _int, row_json
from inkbridge.db.recognitions import _reindex_region

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# How long a second process waits for another one's migration before giving up.
MIGRATE_LOCK_TIMEOUT_MS = 120_000


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending numbered .sql files; return the versions applied by this call.

    The whole run is one BEGIN IMMEDIATE transaction, which doubles as a cross-process lock: a
    second API process or worker starting at the same time waits here, then sees the versions
    the first one recorded and applies nothing. A failure rolls everything back (decision 0010).
    """
    isolation, timeout = conn.isolation_level, conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.isolation_level = None  # manual transactions: the sqlite3 module must not commit for us
    conn.execute(f"PRAGMA busy_timeout = {MIGRATE_LOCK_TIMEOUT_MS}")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            applied = _migrate_locked(conn)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:  # SQLite may already have rolled back (e.g. RAISE(ROLLBACK))
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute(f"PRAGMA busy_timeout = {timeout}")
        conn.isolation_level = isolation
    return applied


def _migrate_locked(conn: sqlite3.Connection) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_version")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"(\d+)_", f.name)
        version = int(m.group(1)) if m else None
        if version is None or version in done:
            continue
        _apply_migration(conn, version, f.read_text())
        applied.append(version)
    if 8 in applied:
        _backfill_scene_rows(conn)  # before the version-4 heals, which read the rows
    if 11 in applied:
        _move_drafts_out_of_scene(conn)
    # Version 4 needs a data backfill. Checking for unfilled rows (rather than "4 was just
    # applied") also heals a database whose backfill was interrupted before this lock existed.
    if (
        4 in done | set(applied)
        and conn.execute("SELECT 1 FROM regions WHERE content_hash IS NULL LIMIT 1").fetchone()
    ):
        _backfill_v2(conn, rows=8 in done | set(applied))
    if 4 in done | set(applied):
        _rekey_integral_hashes(conn, rows=8 in done | set(applied))  # under the migration lock, committed with it
    return applied


def _move_drafts_out_of_scene(conn: sqlite3.Connection) -> None:
    """Migration 0011 (INK-114, decision 0086): drafts leave scene_elements. Pure SQL plus json.

    Draft rows of accepted ops become plain agent ink; rows of `applied` ops move into the op as
    `placed`; any other draft row is soft-deleted; `applied` ops left without elements expire.
    """
    ops = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM agent_ops")}
    for doc in [r[0] for r in conn.execute("SELECT DISTINCT document_id FROM scene_elements")]:
        rows = conn.execute(
            "SELECT id, pos, json FROM scene_elements WHERE document_id = ?"
            " AND json_extract(json, '$.customData.draft') IS NOT NULL"
            " AND json_extract(json, '$.customData.draft') != 0 AND json_extract(json, '$.type') IS NOT NULL",
            (doc,),
        ).fetchall()
        if not rows:
            continue
        head = conn.execute(
            "UPDATE scenes SET version = version + 1 WHERE document_id = ? RETURNING version", (doc,)
        ).fetchone()[0]
        moved: dict[str, list[dict]] = {}
        for r in rows:
            e = json.loads(r["json"])
            op_id = (e.get("customData") or {}).get("op_id") or r["id"].split(":", 1)[0]
            status = ops.get(op_id)
            if status == "applied":
                e["customData"] = {**e["customData"], "op_id": op_id}
                moved.setdefault(op_id, []).append(dict(e))
                e["isDeleted"] = True  # tombstone, so seq-based clients see the removal
            elif status == "accepted":
                e["customData"] = {k: v for k, v in e["customData"].items() if k != "draft"}
            else:
                e["isDeleted"] = True
                log.info("INK-114: dropped orphan draft %s", r["id"])
            e["version"] = _int(e.get("version")) + 1
            e["versionNonce"] = random.getrandbits(31) or 1
            conn.execute(
                "UPDATE scene_elements SET json = ?, version = ?, nonce = ?, is_deleted = ?, seq = ?"
                " WHERE document_id = ? AND id = ?",
                (
                    row_json(e),
                    e["version"],
                    e["versionNonce"],
                    int(bool(e.get("isDeleted"))),
                    head,
                    doc,
                    r["id"],
                ),
            )
        live = [
            json.loads(r["json"])
            for r in conn.execute(
                "SELECT json FROM scene_elements WHERE document_id = ? AND is_deleted = 0"
                " AND json_extract(json, '$.type') IS NOT NULL",
                (doc,),
            )
        ]
        conn.execute(
            "UPDATE scenes SET element_count = ? WHERE document_id = ?",
            (sum(1 for e in live if not (e.get("customData") or {}).get("draft")), doc),
        )
        from inkbridge.db.chunks import _sync_chunks  # local: chunks imports the db package

        _sync_chunks(conn, doc, live, {e["id"]: e for e in live}, {r["id"] for r in rows}, _now(), None)
        for op_id, els in moved.items():
            conn.execute(
                "UPDATE agent_ops SET status = 'placed', elements_json = ?, box_json = ? WHERE id = ?",
                (json.dumps(els), json.dumps(bbox_of(els)), op_id),
            )
            ops[op_id] = "placed"
    conn.execute("UPDATE agent_ops SET status = 'expired' WHERE status = 'applied'")


def _backfill_scene_rows(conn: sqlite3.Connection) -> None:
    """Migration 0008: one row per element of every stored scene, array order kept as `pos`."""
    for scene in conn.execute(
        "SELECT document_id, version, elements_json, updated_at FROM scenes"
    ).fetchall():
        slots: dict[str, tuple[int, dict]] = {}  # a duplicate id keeps the last element, first slot
        for pos, element in enumerate(json.loads(scene["elements_json"])):
            slots[element["id"]] = (slots[element["id"]][0] if element["id"] in slots else pos, element)
        for element_id, (pos, element) in slots.items():
            conn.execute(
                "INSERT INTO scene_elements"
                " (document_id, id, pos, seq, version, nonce, is_deleted, json, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    scene["document_id"],
                    element_id,
                    pos,
                    scene["version"],
                    _int(element.get("version")),
                    _int(element.get("versionNonce")),
                    int(bool(element.get("isDeleted"))),
                    row_json(element),
                    scene["updated_at"],
                ),
            )


def _scene_by_id(conn: sqlite3.Connection, document_id: str, rows: bool) -> dict[str, dict]:
    """A canvas's elements by id: from the rows once migration 0008 exists, else from the blob."""
    if rows:
        found = conn.execute(
            "SELECT json FROM scene_elements WHERE document_id = ? ORDER BY pos", (document_id,)
        ).fetchall()
        elements = (json.loads(r["json"]) for r in found)
        return {e["id"]: e for e in elements if "type" in e or not e.get("isDeleted")}  # not stubs
    row = conn.execute(
        "SELECT elements_json FROM scenes WHERE document_id = ?", (document_id,)
    ).fetchone()
    return {e["id"]: e for e in json.loads(row["elements_json"])} if row else {}


def _apply_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
    # Not executescript: it commits first, which would release the lock mid-run.
    for statement in _statements(sql):
        conn.execute(statement)
    conn.execute("INSERT INTO schema_version VALUES (?)", (version,))


def _statements(sql: str) -> list[str]:
    """Split a script into complete statements (semicolons in strings and triggers are kept)."""
    out, buf = [], ""
    for part in sql.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            out.append(buf)
            buf = ""
    # Whatever is left has no terminating semicolon: comments, whitespace or a last statement.
    if buf[:-1].strip():
        out.append(buf[:-1])
    return out


def _backfill_v2(conn: sqlite3.Connection, rows: bool = False) -> None:
    """After migration 0004: fill content_hash, re-key current readings, add text_hash.

    Old readings were keyed by stroke_hash. A reading whose key equals its region's current
    stroke_hash describes the current ink, so it moves to the current content_hash; older
    readings keep a key that never matches and are simply never selected.
    """
    scenes: dict[str, dict] = {}  # parse each document's scene once, not once per region
    for region in conn.execute("SELECT * FROM regions").fetchall():
        doc = region["document_id"]
        if doc not in scenes:
            scenes[doc] = _scene_by_id(conn, doc, rows)
        by_id = scenes[doc]
        present = [by_id[i] for i in json.loads(region["element_ids_json"]) if i in by_id]
        new_hash = content_hash(present)
        conn.execute("UPDATE regions SET content_hash = ? WHERE id = ?", (new_hash, region["id"]))
        conn.execute(
            "UPDATE recognitions SET content_hash = ? WHERE region_id = ? AND content_hash = ?",
            (new_hash, region["id"], region["stroke_hash"]),
        )
    for rec in conn.execute("SELECT rowid, text, latex FROM recognitions").fetchall():
        conn.execute(
            "UPDATE recognitions SET text_hash = ? WHERE rowid = ?",
            (text_hash(rec["text"], rec["latex"]), rec["rowid"]),
        )
    for region in conn.execute("SELECT id FROM regions").fetchall():
        _reindex_region(conn, region["id"])


def _rekey_integral_hashes(conn: sqlite3.Connection, rows: bool = False) -> None:
    """Move rows hashed before content_hash wrote integral floats as ints to the new key.

    Runs inside migrate()'s transaction on every start. Idempotent: a region is only touched when
    its stored hash is the old form of its current ink and differs from the new form, so the ink
    is identical and its readings (and search hit) carry over instead of being lost on the next
    move.
    """
    scenes: dict[str, dict] = {}
    for region in conn.execute(
        "SELECT id, document_id, element_ids_json, content_hash FROM regions"
    ):
        doc = region["document_id"]
        if doc not in scenes:
            scenes[doc] = _scene_by_id(conn, doc, rows)
        present = [
            scenes[doc][i] for i in json.loads(region["element_ids_json"]) if i in scenes[doc]
        ]
        old, new = region["content_hash"], content_hash(present)
        if old == new or old != legacy_content_hash(present):
            continue
        conn.execute("UPDATE regions SET content_hash = ? WHERE id = ?", (new, region["id"]))
        conn.execute(
            "UPDATE OR IGNORE recognitions SET content_hash = ? WHERE region_id = ? AND content_hash = ?",
            (new, region["id"], old),
        )
        _reindex_region(conn, region["id"])


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        migrate(conn)  # also heals an interrupted v2 backfill and re-keys old content hashes
        ensure_default_document(conn)
    finally:
        conn.close()
