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
