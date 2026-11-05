"""Canvas (document) rows and reading their stored scene."""

import logging
import sqlite3

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import DEFAULT_DOCUMENT_ID, DocumentNotFound, _now


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


def get_scene(conn: sqlite3.Connection, document_id: str) -> tuple[int, str]:
    """Return (version, elements_json) or raise DocumentNotFound."""
    row = conn.execute(
        "SELECT version, elements_json FROM scenes WHERE document_id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return row["version"], row["elements_json"]


def document_exists(conn: sqlite3.Connection, document_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None
    )


def document_updated_at(conn: sqlite3.Connection, document_id: str) -> str | None:
    """When the canvas was last saved (ISO-8601 UTC); None if it does not exist."""
    row = conn.execute("SELECT updated_at FROM documents WHERE id = ?", (document_id,)).fetchone()
    return row["updated_at"] if row else None
