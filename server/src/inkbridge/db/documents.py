"""Canvas (document) rows and reading their stored scene."""

import logging
import sqlite3

from inkbridge import config

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import DEFAULT_DOCUMENT_ID, DocumentNotFound, _now
from inkbridge.db.elements import concat, read_rows


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


def get_scene(
    conn: sqlite3.Connection, document_id: str, *, stubs: bool = False
) -> tuple[int, str]:
    """Return (version, elements_json) or raise DocumentNotFound.

    The elements are every stored element, deleted ones included, in scene order, as a JSON array
    text built from the rows. Tombstone stubs are left out unless `stubs` (INK-110).
    """
    version = scene_version(conn, document_id)
    return version, concat(read_rows(conn, document_id, stubs=stubs))


def get_live_scene(
    conn: sqlite3.Connection, document_id: str, *, include_deleted: bool = False
) -> tuple[int, str, int]:
    """(seq, elements array text, element count) for the scene load: live rows only by default."""
    seq = scene_version(conn, document_id)
    rows = read_rows(conn, document_id, live_only=not include_deleted)
    return seq, concat(rows), len(rows)


def scene_changes(conn: sqlite3.Connection, document_id: str, since: int) -> tuple[int, str, int]:
    """(head seq, array text, count) of every row written after `since`, deleted rows and stubs too."""
    head = scene_version(conn, document_id)
    rows = read_rows(conn, document_id, stubs=True, since=since)
    return head, concat(rows), len(rows)


def scene_version(conn: sqlite3.Connection, document_id: str) -> int:
    """The stored scene version without loading the elements, or raise DocumentNotFound."""
    row = conn.execute(
        "SELECT version FROM scenes WHERE document_id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return row["version"]


def document_exists(conn: sqlite3.Connection, document_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None
    )


def document_updated_at(conn: sqlite3.Connection, document_id: str) -> str | None:
    """When the canvas was last saved (ISO-8601 UTC); None if it does not exist."""
    row = conn.execute("SELECT updated_at FROM documents WHERE id = ?", (document_id,)).fetchone()
    return row["updated_at"] if row else None


# INK-118 (decision 0069): one row per canvas for the home screen. element_count is stored by
# put_scene, so a list never parses a scene; the other counts are indexed lookups.
_SUMMARY = """
SELECT d.id, d.title, d.updated_at, d.pinned, d.archived_at, d.last_opened_at, d.chunker,
       COALESCE(s.version, 0) AS version,
       COALESCE(s.element_count, 0) AS element_count,
       (SELECT COUNT(*) FROM regions r WHERE r.document_id = d.id
          AND r.created_by = 'auto' AND r.status = 'active') AS chunk_count,
       (SELECT COUNT(*) FROM agent_ops o WHERE o.document_id = d.id
          AND o.status IN ('pending', 'delivered', 'applied')) AS open_offers
FROM documents d LEFT JOIN scenes s ON s.document_id = d.id"""

_ARCHIVE_FILTER = {
    "false": " WHERE d.archived_at IS NULL",
    "true": " WHERE d.archived_at IS NOT NULL",
    "all": "",
}


def _summary(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "pinned": bool(r["pinned"]),
        "archived": r["archived_at"] is not None,
        "element_count": r["element_count"],
        "chunk_count": r["chunk_count"],
        "open_offers": r["open_offers"],
        "last_opened_at": r["last_opened_at"],
        "chunker": r["chunker"] or config.chunker(),
    }


def list_documents(conn: sqlite3.Connection, archived: str = "false") -> list[dict]:
    """Canvases, most recently updated first. archived: 'false' (default), 'true' or 'all'."""
    if archived not in _ARCHIVE_FILTER:
        raise ValueError(f"archived must be one of {tuple(_ARCHIVE_FILTER)}, got {archived!r}")
    sql = _SUMMARY + _ARCHIVE_FILTER[archived] + " ORDER BY d.updated_at DESC, d.id"
    return [_summary(r) for r in conn.execute(sql)]


def document_summary(conn: sqlite3.Connection, document_id: str) -> dict:
    row = conn.execute(_SUMMARY + " WHERE d.id = ?", (document_id,)).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return _summary(row)


def patch_document(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    title: str | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict:
    """Rename, pin or archive. Never touches updated_at (that means the last ink edit)."""
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    if title is not None:
        conn.execute("UPDATE documents SET title = ? WHERE id = ?", (title, document_id))
    if pinned is not None:
        conn.execute("UPDATE documents SET pinned = ? WHERE id = ?", (int(pinned), document_id))
    if archived is True:
        conn.execute(
            "UPDATE documents SET archived_at = COALESCE(archived_at, ?) WHERE id = ?",
            (_now(), document_id),
        )
    elif archived is False:
        conn.execute("UPDATE documents SET archived_at = NULL WHERE id = ?", (document_id,))
    conn.commit()
    return document_summary(conn, document_id)


def get_chunker(conn: sqlite3.Connection, document_id: str) -> str:
    """'v1' or 'v2' for a canvas: its own setting, else INKBRIDGE_CHUNKER, else v1 (INK-122)."""
    row = conn.execute("SELECT chunker FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return row["chunker"] or config.chunker()


def mark_opened(conn: sqlite3.Connection, document_id: str) -> None:
    cur = conn.execute(
        "UPDATE documents SET last_opened_at = ? WHERE id = ?", (_now(), document_id)
    )
    if cur.rowcount == 0:
        raise DocumentNotFound(document_id)
    conn.commit()
