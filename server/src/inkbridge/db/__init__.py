"""SQLite access. The only module that touches the database; the MCP server must not import it."""

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from inkbridge import config
from inkbridge.chunker import ChunkerConfig, chunk_scene, connector_ids, kind_hint, match_chunks
from inkbridge.regions import (
    bbox_of,
    content_hash,
    legacy_content_hash,
    stroke_hash,
    text_hash,
)

DEFAULT_DOCUMENT_ID = "default"
RECOGNITION_SOURCES = ("user", "agent", "gemini")
AUTO = "auto"  # regions.created_by of chunks the chunker owns; anything else is a manual region
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers do not block behind the scene writer
    return conn


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
    # Version 4 needs a data backfill. Checking for unfilled rows (rather than "4 was just
    # applied") also heals a database whose backfill was interrupted before this lock existed.
    if (
        4 in done | set(applied)
        and conn.execute("SELECT 1 FROM regions WHERE content_hash IS NULL LIMIT 1").fetchone()
    ):
        _backfill_v2(conn)
    if 4 in done | set(applied):
        _rekey_integral_hashes(conn)  # under the migration lock, committed with it
    return applied


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


def _backfill_v2(conn: sqlite3.Connection) -> None:
    """After migration 0004: fill content_hash, re-key current readings, add text_hash.

    Old readings were keyed by stroke_hash. A reading whose key equals its region's current
    stroke_hash describes the current ink, so it moves to the current content_hash; older
    readings keep a key that never matches and are simply never selected.
    """
    scenes: dict[str, dict] = {}  # parse each document's scene once, not once per region
    for region in conn.execute("SELECT * FROM regions").fetchall():
        doc = region["document_id"]
        if doc not in scenes:
            row = conn.execute(
                "SELECT elements_json FROM scenes WHERE document_id = ?", (doc,)
            ).fetchone()
            scenes[doc] = {e["id"]: e for e in json.loads(row["elements_json"])} if row else {}
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


def _rekey_integral_hashes(conn: sqlite3.Connection) -> None:
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
            row = conn.execute(
                "SELECT elements_json FROM scenes WHERE document_id = ?", (doc,)
            ).fetchone()
            scenes[doc] = {e["id"]: e for e in json.loads(row["elements_json"])} if row else {}
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


def ensure_default_document(conn: sqlite3.Connection) -> None:
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO documents (id, title, updated_at) VALUES (?, ?, ?)",
        (DEFAULT_DOCUMENT_ID, "Untitled", now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO scenes (document_id, version, elements_json, updated_at)"
        " VALUES (?, 0, '[]', ?)",
        (DEFAULT_DOCUMENT_ID, now),
    )
    conn.commit()


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        migrate(conn)  # also heals an interrupted v2 backfill and re-keys old content hashes
        ensure_default_document(conn)
    finally:
        conn.close()


class DocumentNotFound(Exception):
    pass


class VersionConflict(Exception):
    def __init__(self, current_version: int):
        super().__init__(f"scene is at version {current_version}")
        self.current_version = current_version


def get_scene(conn: sqlite3.Connection, document_id: str) -> tuple[int, str]:
    """Return (version, elements_json) or raise DocumentNotFound."""
    row = conn.execute(
        "SELECT version, elements_json FROM scenes WHERE document_id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return row["version"], row["elements_json"]


def put_scene(
    conn: sqlite3.Connection,
    document_id: str,
    base_version: int,
    elements_json: str,
    chunker_config: ChunkerConfig | None = None,
) -> int:
    """Store the scene if base_version is current; return the new version.

    BEGIN IMMEDIATE takes the write lock before the old scene is read, and the UPDATE compares
    the version again, so two writers with the same base_version cannot both win even if one
    guard is lost. Regions and chunks are re-derived in the same transaction, so they never
    disagree with the stored scene; any error rolls the whole save back.
    """
    now = _now()
    conn.execute("BEGIN IMMEDIATE")  # read the old scene and replace it under one write lock
    try:
        old = conn.execute(
            "SELECT version, elements_json FROM scenes WHERE document_id = ?", (document_id,)
        ).fetchone()
        if old is None:
            raise DocumentNotFound(document_id)
        if old["version"] != base_version:
            raise VersionConflict(old["version"])
        cur = conn.execute(
            "UPDATE scenes SET version = version + 1, elements_json = ?, updated_at = ?"
            " WHERE document_id = ? AND version = ?",
            (elements_json, now, document_id, base_version),
        )
        if cur.rowcount == 0:  # second guard: only reachable if the write lock was not held
            raise VersionConflict(get_scene(conn, document_id)[0])
        elements = json.loads(elements_json)
        by_id = {e["id"]: e for e in elements}
        changed = _changed_ids(json.loads(old["elements_json"]), by_id)
        _refresh_regions(conn, document_id, by_id, changed, now)
        _sync_chunks(conn, document_id, elements, by_id, changed, now, chunker_config)
        conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return base_version + 1


def _changed_ids(old_elements: list[dict], new_by_id: dict[str, dict]) -> set[str]:
    """Ids added, removed or edited since the last save (tech ref gap 7).

    Excalidraw bumps `version` on every edit, but comparing whole elements is just as cheap on
    parsed JSON and stays right for clients that do not bump it. Volatile-field churn counts as a
    change here; the hashes then come out equal and nothing is written.
    """
    old_by_id = {e["id"]: e for e in old_elements}
    changed = {i for i, e in new_by_id.items() if old_by_id.get(i) != e}
    return changed | (old_by_id.keys() - new_by_id.keys())


class ReservedCreator(ValueError):
    """created_by='auto' marks chunker-owned rows and cannot be used for a manual region."""


class UnknownElements(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"elements not in scene: {ids}")
        self.ids = ids


# Precedence: user > agent > gemini.
_BEST_RECOGNITION = """
    SELECT text, latex, source, text_hash FROM recognitions
    WHERE region_id = ? AND content_hash = ?
    ORDER BY CASE source WHEN 'user' THEN 0 WHEN 'agent' THEN 1 ELSE 2 END, created_at DESC
    LIMIT 1
"""


def _region_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    rec = conn.execute(_BEST_RECOGNITION, (row["id"], row["content_hash"])).fetchone()
    ids = json.loads(row["element_ids_json"])
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "element_ids": ids,
        "bounds": json.loads(row["bbox"]),
        "stroke_count": len(ids),
        "kind": row["kind"],
        "created_by": row["created_by"],
        "stroke_hash": row["stroke_hash"],
        "content_hash": row["content_hash"],
        "status": row["status"],
        "successor_of": row["successor_of"],
        "png_stale": bool(row["png_stale"]),
        "updated_at": row["updated_at"],
        "text": rec["text"] if rec else None,
        "latex": rec["latex"] if rec else None,
        "source": rec["source"] if rec else None,
        "text_hash": rec["text_hash"] if rec else None,
    }


def create_region(
    conn: sqlite3.Connection,
    document_id: str,
    element_ids: list[str],
    png_path: str,
    kind: str | None = None,
    created_by: str = "user",
    region_id: str | None = None,
) -> dict:
    """Create a region; bbox and stroke_hash are computed from the stored scene, never the client."""
    conn.execute("BEGIN IMMEDIATE")  # read the scene and insert under one write lock
    try:
        return _create_region(conn, document_id, element_ids, png_path, kind, created_by, region_id)
    except BaseException:
        conn.rollback()
        raise


def _create_region(conn, document_id, element_ids, png_path, kind, created_by, region_id):
    if created_by == AUTO:
        raise ReservedCreator(AUTO)  # the chunker owns these rows; it would adopt or orphan it
    _, elements_json = get_scene(conn, document_id)
    by_id = {e["id"]: e for e in json.loads(elements_json)}
    missing = [i for i in element_ids if i not in by_id]
    if missing:
        raise UnknownElements(missing)
    chosen = [by_id[i] for i in element_ids]
    rid = region_id or uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO regions (id, document_id, element_ids_json, bbox, kind, created_by,"
        " stroke_hash, content_hash, png_path, status, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'active',?)",
        (
            rid,
            document_id,
            json.dumps(element_ids),
            json.dumps(bbox_of(chosen)),
            kind,
            created_by,
            stroke_hash(chosen),
            content_hash(chosen),
            png_path,
            _now(),
        ),
    )
    conn.commit()
    return get_region(conn, rid)


def get_region(conn: sqlite3.Connection, region_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
    return _region_dict(conn, row) if row else None


def get_region_png_path(conn: sqlite3.Connection, region_id: str) -> str | None:
    row = conn.execute("SELECT png_path FROM regions WHERE id = ?", (region_id,)).fetchone()
    return row["png_path"] if row else None


def list_regions(
    conn: sqlite3.Connection,
    document_id: str,
    kind: str | None = None,
    limit: int = 100,
    chunks: bool = False,
) -> list[dict]:
    """Manual regions, or with chunks=True the auto chunks (both kinds via get_region by id)."""
    sql = "SELECT * FROM regions WHERE document_id = ? AND created_by IS " + (
        "?" if chunks else "NOT ?"
    )
    args: list = [document_id, AUTO]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    sql += " ORDER BY updated_at DESC, id LIMIT ?"
    args.append(limit)
    return [_region_dict(conn, r) for r in conn.execute(sql, args)]


def _refresh_regions(
    conn: sqlite3.Connection,
    document_id: str,
    by_id: dict[str, dict],
    changed: set[str],
    now: str,
) -> None:
    """Re-derive hash/status of the document's manual regions from a new scene (same transaction).

    Only regions holding a changed element are looked at, and a region is only written when a hash
    or its status actually changed, so unrelated edits and volatile-field churn leave it (and its
    updated_at) alone. A new stroke_hash means the crop PNG is flagged stale until the client
    saves it again; a new content_hash means the ink itself changed, so the old reading no longer
    applies and a new recognition is needed. A pure move changes only the stroke_hash: the reading
    and its search hit stay. Auto chunks are kept by _sync_chunks instead.
    """
    if not changed:
        return
    for row in conn.execute(
        "SELECT * FROM regions WHERE document_id = ? AND created_by IS NOT ?", (document_id, AUTO)
    ).fetchall():
        ids = json.loads(row["element_ids_json"])
        if changed.isdisjoint(ids):
            continue
        present = [by_id[i] for i in ids if i in by_id]
        new_hash = stroke_hash(present)
        new_content = content_hash(present)
        alive = any(not e.get("isDeleted") for e in present)
        new_status = "active" if alive else "orphaned"
        if (
            new_hash == row["stroke_hash"]
            and new_content == row["content_hash"]
            and new_status == row["status"]
        ):
            continue
        bbox = json.dumps(bbox_of(present)) if present else row["bbox"]
        conn.execute(
            "UPDATE regions SET stroke_hash = ?, content_hash = ?, bbox = ?, status = ?,"
            " updated_at = ?,"
            " png_stale = CASE WHEN ? != stroke_hash THEN 1 ELSE png_stale END WHERE id = ?",
            (new_hash, new_content, bbox, new_status, now, new_hash, row["id"]),
        )
        if new_content != row["content_hash"]:
            _reindex_region(conn, row["id"])  # old reading no longer describes the ink


def _sync_chunks(
    conn: sqlite3.Connection,
    document_id: str,
    elements: list[dict],
    by_id: dict[str, dict],
    changed: set[str],
    now: str,
    chunker_config: ChunkerConfig | None,
) -> None:
    """Re-run the chunker and upsert one created_by='auto' region per chunk (tech ref 5.5-5.8).

    New clusters inherit ids from old chunks (orphaned ones too, so undo reactivates them) by
    element-id Jaccard. A kept chunk whose element set is unchanged and holds no changed element
    is skipped without hashing. Chunks that lose their id become orphaned, keep their last
    element ids and hashes, and point successor_of at the cluster that took most of their ink.
    """
    cfg = chunker_config or ChunkerConfig()
    chunking = chunk_scene(elements, cfg)
    clusters = chunking.chunks
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT * FROM regions WHERE document_id = ? AND created_by = ?", (document_id, AUTO)
        ).fetchall()
    }
    old = {rid: json.loads(r["element_ids_json"]) for rid, r in rows.items()}
    boxes = [bbox_of([by_id[i] for i in members]) for members in clusters]
    matching = match_chunks(
        old,
        clusters,
        tops=[b["y"] for b in boxes],
        active={rid for rid, r in rows.items() if r["status"] == "active"},
        threshold=cfg.match_threshold,
        ignore=connector_ids(elements),
    )
    ids = [rid or uuid.uuid4().hex[:12] for rid in matching.assigned]

    for rid, kept, members, box in zip(ids, matching.assigned, clusters, boxes, strict=True):
        row = rows.get(kept) if kept else None
        # Kept, still active and holding exactly the same elements as before.
        same = row is not None and row["status"] == "active" and old[rid] == members
        if same and changed.isdisjoint(members):
            continue  # same elements, none edited: nothing to recompute
        chunk = [by_id[i] for i in members]
        new_stroke, new_content = stroke_hash(chunk), content_hash(chunk)
        if row is None:
            conn.execute(
                "INSERT INTO regions (id, document_id, element_ids_json, bbox, kind, created_by,"
                " stroke_hash, content_hash, png_path, status, png_stale, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,'active',1,?)",
                (
                    rid,
                    document_id,
                    json.dumps(members),
                    json.dumps(box),
                    kind_hint(chunk),
                    AUTO,
                    new_stroke,
                    new_content,
                    str(config.crops_dir() / f"{rid}.png"),
                    now,
                ),
            )
            continue
        if same and new_stroke == row["stroke_hash"] and new_content == row["content_hash"]:
            continue  # only volatile fields moved
        content_changed = new_content != row["content_hash"]
        conn.execute(
            "UPDATE regions SET element_ids_json = ?, bbox = ?, stroke_hash = ?,"
            " content_hash = ?, kind = ?, status = 'active', successor_of = NULL,"
            " updated_at = ?,"
            " png_stale = CASE WHEN ? != stroke_hash THEN 1 ELSE png_stale END WHERE id = ?",
            (
                json.dumps(members),
                json.dumps(box),
                new_stroke,
                new_content,
                kind_hint(chunk) if content_changed else row["kind"],
                now,
                new_stroke,
                rid,
            ),
        )
        if content_changed:
            _reindex_region(conn, rid)  # no reading for the new ink yet: drop the search row

    for rid, successor in matching.successors.items():
        conn.execute(
            "UPDATE regions SET status = 'orphaned', successor_of = ?, updated_at = ? WHERE id = ?",
            (ids[successor] if successor is not None else None, now, rid),
        )

    # Links are derived state: rebuilt from scratch, so they only ever name current chunks.
    conn.execute("DELETE FROM links WHERE document_id = ?", (document_id,))
    conn.executemany(
        "INSERT INTO links (document_id, from_region, to_region, kind) VALUES (?, ?, ?, 'arrow')",
        [(document_id, ids[a], ids[b]) for a, b in chunking.links],
    )


def list_links(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Links between the document's current chunks, as {from, to, kind}."""
    return [
        {"from": r["from_region"], "to": r["to_region"], "kind": r["kind"]}
        for r in conn.execute(
            "SELECT from_region, to_region, kind FROM links WHERE document_id = ?"
            " ORDER BY from_region, to_region, kind",
            (document_id,),
        )
    ]


def get_region_ink(conn: sqlite3.Connection, region_id: str) -> dict | None:
    """Raw stroke points/pressures of a region's live elements, from the current scene."""
    region = get_region(conn, region_id)
    if region is None:
        return None
    _, elements_json = get_scene(conn, region["document_id"])
    by_id = {e["id"]: e for e in json.loads(elements_json)}
    strokes = [
        {
            "id": i,
            "x": by_id[i].get("x", 0),
            "y": by_id[i].get("y", 0),
            "angle": by_id[i].get("angle", 0),
            "points": by_id[i].get("points", []),
            "pressures": by_id[i].get("pressures", []),
        }
        for i in region["element_ids"]
        if i in by_id and not by_id[i].get("isDeleted")
    ]
    return {"strokes": strokes, "point_count": sum(len(s["points"]) for s in strokes)}


def get_sketch_elements(conn: sqlite3.Connection, region_id: str) -> list[dict] | None:
    """Live, non-draft elements of a region plus those of regions an arrow links it to (one hop).

    A sketched flowchart with long arrows splits into one chunk per node joined by `links`, so
    reading one chunk alone would leave every arrow without a target. None if the region is unknown.
    """
    region = get_region(conn, region_id)
    if region is None:
        return None
    ids = list(region["element_ids"])
    for row in conn.execute(
        "SELECT from_region, to_region FROM links WHERE from_region = ? OR to_region = ?"
        " LIMIT 50",  # a hub chunk must not pull in the whole canvas
        (region_id, region_id),
    ):
        other = row["to_region"] if row["from_region"] == region_id else row["from_region"]
        linked = get_region(conn, other)
        if linked is not None and linked["status"] == "active":
            ids += linked["element_ids"]
    _, elements_json = get_scene(conn, region["document_id"])
    by_id = {e["id"]: e for e in json.loads(elements_json)}
    out, seen = [], set()
    for i in ids:
        e = by_id.get(i)
        if e is None or i in seen or e.get("isDeleted") or (e.get("customData") or {}).get("draft"):
            continue
        seen.add(i)
        out.append(e)
    return out


def _reindex_region(conn: sqlite3.Connection, region_id: str) -> None:
    """Make region_fts hold the best reading for the region's current content_hash (or nothing)."""
    conn.execute("DELETE FROM region_fts WHERE region_id = ?", (region_id,))
    region = conn.execute(
        "SELECT document_id, content_hash FROM regions WHERE id = ?", (region_id,)
    ).fetchone()
    if region is None:
        return
    rec = conn.execute(_BEST_RECOGNITION, (region_id, region["content_hash"])).fetchone()
    if rec and (rec["text"] or rec["latex"]):
        conn.execute(
            "INSERT INTO region_fts (region_id, document_id, text, latex) VALUES (?,?,?,?)",
            (region_id, region["document_id"], rec["text"] or "", rec["latex"] or ""),
        )


def save_recognition(
    conn: sqlite3.Connection,
    region_id: str,
    content_hash_: str,
    source: str,
    text: str | None,
    latex: str | None = None,
    model: str | None = None,
) -> None:
    """Upsert a reading keyed by (region, content_hash, source); refresh the search index."""
    if source not in RECOGNITION_SOURCES:
        raise ValueError(f"source must be one of {RECOGNITION_SOURCES}, got {source!r}")
    conn.execute(
        "INSERT INTO recognitions"
        " (region_id, content_hash, source, model, text, latex, text_hash, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(region_id, content_hash, source) DO UPDATE SET"
        " model = excluded.model, text = excluded.text, latex = excluded.latex,"
        " text_hash = excluded.text_hash, created_at = excluded.created_at",
        (region_id, content_hash_, source, model, text, latex, text_hash(text, latex), _now()),
    )
    _reindex_region(conn, region_id)
    conn.commit()


def _fts_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 expression: quoted prefix tokens, implicitly ANDed."""
    tokens = re.findall(r"\w+", q)
    return " ".join(f'"{t}"*' for t in tokens) or None


def search(
    conn: sqlite3.Connection, query: str, limit: int = 20, document_id: str | None = None
) -> list[dict]:
    match = _fts_query(query)
    if match is None:
        return []
    sql = (
        "SELECT region_fts.region_id AS region_id,"
        " snippet(region_fts, -1, '[', ']', '…', 12) AS snippet,"
        " -bm25(region_fts) AS score"
        " FROM region_fts JOIN regions r ON r.id = region_fts.region_id"
        " WHERE region_fts MATCH ? AND r.status = 'active'"
    )
    args: list = [match]
    if document_id:
        sql += " AND r.document_id = ?"
        args.append(document_id)
    sql += " ORDER BY bm25(region_fts) LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def document_exists(conn: sqlite3.Connection, document_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None
    )


def mark_png_fresh(conn: sqlite3.Connection, region_id: str) -> dict | None:
    """Clear png_stale after the client has saved a new crop; None if the region is unknown."""
    cur = conn.execute("UPDATE regions SET png_stale = 0 WHERE id = ?", (region_id,))
    conn.commit()
    return get_region(conn, region_id) if cur.rowcount else None


def stale_crop_ids(conn: sqlite3.Connection, document_id: str) -> list[str]:
    """Active regions whose crop no longer matches their ink (the browser re-exports them)."""
    rows = conn.execute(
        "SELECT id FROM regions WHERE document_id = ? AND status = 'active' AND png_stale = 1"
        " ORDER BY id",
        (document_id,),
    )
    return [r["id"] for r in rows]
