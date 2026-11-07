"""Which chunk readings a vault note was written from (INK-132, decision 0091). Hashes only."""

import sqlite3

from inkbridge.db.common import DocumentNotFound, _now


def put_watch(
    conn: sqlite3.Connection, document_id: str, note_id: str, chunks: list[tuple[str, str]]
) -> int:
    """Replace the note's rows with (chunk_id, reading_hash) pairs."""
    if conn.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone() is None:
        raise DocumentNotFound(document_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "DELETE FROM watches WHERE document_id=? AND note_id=?", (document_id, note_id)
        )
        now = _now()
        conn.executemany(
            "INSERT OR REPLACE INTO watches (document_id, note_id, chunk_id, reading_hash, created_at)"
            " VALUES (?,?,?,?,?)",
            [(document_id, note_id, cid, h, now) for cid, h in chunks],
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return len(chunks)


def list_watches(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT note_id, chunk_id, reading_hash FROM watches WHERE document_id=?"
            " ORDER BY note_id, chunk_id",
            (document_id,),
        )
    ]
