"""Recognition cache, full-text index and search."""

import logging
import re
import sqlite3

from inkbridge.canvas.hashes import (
    text_hash,
)

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import AUTO, _now

RECOGNITION_SOURCES = ("user", "agent", "gemini")


# Precedence: user > agent > gemini.
_BEST_RECOGNITION = """
    SELECT text, latex, source, text_hash FROM recognitions
    WHERE region_id = ? AND content_hash = ?
    ORDER BY CASE source WHEN 'user' THEN 0 WHEN 'agent' THEN 1 ELSE 2 END, created_at DESC
    LIMIT 1
"""


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
    _put_recognition(conn, region_id, content_hash_, source, text, latex, model)
    conn.commit()


def _put_recognition(
    conn: sqlite3.Connection,
    region_id: str,
    content_hash_: str,
    source: str,
    text: str | None,
    latex: str | None = None,
    model: str | None = None,
) -> None:
    """save_recognition without the commit, so a scene save can write it in its transaction."""
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


def recognition_candidates(
    conn: sqlite3.Connection, document_id: str, include_stale: bool = False
) -> list[dict]:
    """Active regions the recognizer should read now (INK-014).

    Fresh crop (png_stale = 0; with include_stale the server renders it first, INK-120) and no reading of any source for the current content_hash: moved
    ink keeps its content_hash and so its reading, and a user or agent reading needs no model call.
    """
    fresh = "" if include_stale else " AND r.png_stale = 0"
    rows = conn.execute(
        "SELECT r.id, r.content_hash, r.png_path, r.bbox, r.element_ids_json FROM regions r"
        f" WHERE r.document_id = ? AND r.status = 'active'{fresh}"
        " AND r.content_hash IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM recognitions c"
        "  WHERE c.region_id = r.id AND c.content_hash = r.content_hash)"
        " ORDER BY r.updated_at, r.id",
        (document_id,),
    )
    return [dict(r) for r in rows]


def save_model_reading(
    conn: sqlite3.Connection, region_id: str, content_hash_: str, reading
) -> None:
    """Store a model reading (source='gemini') for the hash it was made from, in one commit.

    An auto chunk whose ink is still that hash also takes the model's kind; a manual region keeps
    the kind its creator gave it.
    """
    conn.execute(
        "UPDATE regions SET kind = ? WHERE id = ? AND created_by = ? AND content_hash = ?",
        (reading.kind, region_id, AUTO, content_hash_),
    )
    save_recognition(
        conn, region_id, content_hash_, "gemini", reading.text, reading.latex, reading.model
    )
