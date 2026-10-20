"""SQLite access. The only module that touches the database; the MCP server must not import it."""

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from inkbridge import config
from inkbridge.regions import bbox_of, stroke_hash

DEFAULT_DOCUMENT_ID = "default"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending numbered .sql files; return the versions applied by this call."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_version")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"(\d+)_", f.name)
        version = int(m.group(1)) if m else None
        if version is None or version in done:
            continue
        # executescript commits first, so wrap file + version row in one explicit transaction.
        conn.executescript(
            f"BEGIN;\n{f.read_text()}\nINSERT INTO schema_version VALUES ({version});\nCOMMIT;"
        )
        applied.append(version)
    return applied


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
        migrate(conn)
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
    conn: sqlite3.Connection, document_id: str, base_version: int, elements_json: str
) -> int:
    """Store the scene if base_version is current; return the new version.

    The compare-and-bump is one UPDATE, so two writers with the same base_version cannot both win.
    """
    now = _now()
    cur = conn.execute(
        "UPDATE scenes SET version = version + 1, elements_json = ?, updated_at = ?"
        " WHERE document_id = ? AND version = ?",
        (elements_json, now, document_id, base_version),
    )
    if cur.rowcount == 0:
        current, _ = get_scene(conn, document_id)  # raises DocumentNotFound if missing
        conn.rollback()
        raise VersionConflict(current)
    _refresh_regions(conn, document_id, json.loads(elements_json), now)
    conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
    conn.commit()
    return base_version + 1


class UnknownElements(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"elements not in scene: {ids}")
        self.ids = ids


# Precedence: user > agent > gemini.
_BEST_RECOGNITION = """
    SELECT text, latex, source FROM recognitions
    WHERE region_id = ? AND stroke_hash = ?
    ORDER BY CASE source WHEN 'user' THEN 0 WHEN 'agent' THEN 1 ELSE 2 END, created_at DESC
    LIMIT 1
"""


def _region_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    rec = conn.execute(_BEST_RECOGNITION, (row["id"], row["stroke_hash"])).fetchone()
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
        "status": row["status"],
        "png_stale": bool(row["png_stale"]),
        "updated_at": row["updated_at"],
        "text": rec["text"] if rec else None,
        "latex": rec["latex"] if rec else None,
        "source": rec["source"] if rec else None,
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
    _, elements_json = get_scene(conn, document_id)
    by_id = {e["id"]: e for e in json.loads(elements_json)}
    missing = [i for i in element_ids if i not in by_id]
    if missing:
        raise UnknownElements(missing)
    chosen = [by_id[i] for i in element_ids]
    rid = region_id or uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO regions (id, document_id, element_ids_json, bbox, kind, created_by,"
        " stroke_hash, png_path, status, updated_at) VALUES (?,?,?,?,?,?,?,?,'active',?)",
        (
            rid,
            document_id,
            json.dumps(element_ids),
            json.dumps(bbox_of(chosen)),
            kind,
            created_by,
            stroke_hash(chosen),
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
    conn: sqlite3.Connection, document_id: str, kind: str | None = None, limit: int = 100
) -> list[dict]:
    sql = "SELECT * FROM regions WHERE document_id = ?"
    args: list = [document_id]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    sql += " ORDER BY updated_at DESC, id LIMIT ?"
    args.append(limit)
    return [_region_dict(conn, r) for r in conn.execute(sql, args)]


def _refresh_regions(
    conn: sqlite3.Connection, document_id: str, elements: list[dict], now: str
) -> None:
    """Re-derive hash/status of the document's regions from a new scene (same transaction).

    A region is only written when its hash or status actually changed, so unrelated edits and
    volatile-field churn leave it (and its updated_at) alone. A new hash means a new recognition
    is needed; the crop PNG is flagged stale until the client saves it again.
    """
    by_id = {e["id"]: e for e in elements}
    for row in conn.execute(
        "SELECT * FROM regions WHERE document_id = ?", (document_id,)
    ).fetchall():
        present = [by_id[i] for i in json.loads(row["element_ids_json"]) if i in by_id]
        new_hash = stroke_hash(present)
        alive = any(not e.get("isDeleted") for e in present)
        new_status = "active" if alive else "orphaned"
        if new_hash == row["stroke_hash"] and new_status == row["status"]:
            continue
        bbox = json.dumps(bbox_of(present)) if present else row["bbox"]
        conn.execute(
            "UPDATE regions SET stroke_hash = ?, bbox = ?, status = ?, updated_at = ?,"
            " png_stale = CASE WHEN ? != stroke_hash THEN 1 ELSE png_stale END WHERE id = ?",
            (new_hash, bbox, new_status, now, new_hash, row["id"]),
        )
