"""Regions: manual regions and the shared region row helpers."""

import json
import logging
import sqlite3
import uuid

from inkbridge.canvas.hashes import (
    bbox_of,
    content_hash,
    stroke_hash,
)

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import AUTO, _now
from inkbridge.db.documents import get_scene
from inkbridge.db.recognitions import _BEST_RECOGNITION, _reindex_region


class ReservedCreator(ValueError):
    """created_by='auto' marks chunker-owned rows and cannot be used for a manual region."""


class UnknownElements(Exception):
    def __init__(self, ids: list[str]):
        super().__init__(f"elements not in scene: {ids}")
        self.ids = ids


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
        "pinned": bool(row["pinned"]),
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


def active_chunk_bounds(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Bounding boxes {x, y, width, height} of the active auto chunks, for the home thumbnail (INK-179)."""
    rows = conn.execute(
        "SELECT bbox FROM regions WHERE document_id = ? AND created_by = ? AND status = 'active'"
        " AND bbox IS NOT NULL ORDER BY id",
        (document_id, AUTO),
    )
    return [json.loads(r["bbox"]) for r in rows]


def list_regions(
    conn: sqlite3.Connection,
    document_id: str,
    kind: str | None = None,
    limit: int = 100,
    chunks: bool = False,
    png_stale: bool | None = None,
    status: str | None = None,
) -> list[dict]:
    """Manual regions, or with chunks=True the auto chunks (both kinds via get_region by id).

    png_stale filters on the crop flag; the browser's crop sync lists png_stale=True (INK-057).
    """
    sql = "SELECT * FROM regions WHERE document_id = ? AND created_by IS " + (
        "?" if chunks else "NOT ?"
    )
    args: list = [document_id, AUTO]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if png_stale is not None:
        sql += " AND png_stale = ?"
        args.append(int(png_stale))
    if status:
        sql += " AND status = ?"
        args.append(status)
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
