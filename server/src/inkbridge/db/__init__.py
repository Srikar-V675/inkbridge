"""SQLite access. The only module that touches the database; the MCP server must not import it."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from inkbridge import config

DEFAULT_DOCUMENT_ID = "default"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
    conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
    conn.commit()
    return base_version + 1
