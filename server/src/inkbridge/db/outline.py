"""Canvases and the chunk outline (INK-033): what read_canvas and the export skill read."""

import json
import sqlite3
import uuid

from inkbridge import imaging
from inkbridge.canvas.chunker import reading_order
from inkbridge.db.common import AUTO, DocumentNotFound, _now
from inkbridge.db.documents import document_summary, get_scene
from inkbridge.db.regions import _region_dict
from inkbridge.db.scenes import put_scene

STATUSES = ("active", "orphaned", "all")


MAX_DOCUMENTS = 500  # canvases in all: an agent loop calling create_canvas cannot fill the disk


class TooManyDocuments(Exception):
    pass


def create_document(conn: sqlite3.Connection, title: str) -> dict:
    """A new, empty canvas (scene at version 0) with a fresh 12-hex id."""
    if conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] >= MAX_DOCUMENTS:
        raise TooManyDocuments()
    doc_id, now = uuid.uuid4().hex[:12], _now()
    conn.execute(
        "INSERT INTO documents (id, title, updated_at) VALUES (?, ?, ?)", (doc_id, title, now)
    )
    conn.execute(
        "INSERT INTO scenes (document_id, version, elements_json, updated_at) VALUES (?, 0, '[]', ?)",
        (doc_id, now),
    )
    conn.commit()
    return document_summary(conn, doc_id)


def duplicate_document(conn: sqlite3.Connection, document_id: str) -> dict:
    """A copy of the live, non-draft ink under a new id. Goes through put_scene, so chunks,
    hashes and the search index are derived exactly as for any save. Questions, ops and
    recognitions are not copied (INK-118)."""
    _, raw = get_scene(conn, document_id)  # DocumentNotFound passes through
    src = document_summary(conn, document_id)
    live = [
        e
        for e in json.loads(raw)
        if not e.get("isDeleted") and not (e.get("customData") or {}).get("draft")
    ]
    new = create_document(conn, (src["title"] + " copy")[:200])  # raises TooManyDocuments
    put_scene(conn, new["id"], 0, json.dumps(live, ensure_ascii=False, separators=(",", ":")))
    return document_summary(conn, new["id"])


def chunk_outline(
    conn: sqlite3.Connection,
    document_id: str,
    status: str = "active",
    png_stale: bool | None = None,
) -> dict:
    """The canvas's chunks in reading order, each with its reading, hashes and outgoing links.

    `order` (1-based) is the position among the canvas's active chunks, computed before any filter,
    so a filtered list still says where each chunk sits on the page. Orphaned chunks (status
    'orphaned' or 'all') have no order and follow the active ones by id. Raises DocumentNotFound.
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    row = conn.execute(
        "SELECT version FROM scenes WHERE document_id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    version = row["version"]
    chunks = {
        r["id"]: _region_dict(conn, r)
        for r in conn.execute(
            "SELECT * FROM regions WHERE document_id = ? AND created_by = ?", (document_id, AUTO)
        )
    }
    links: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT DISTINCT from_region, to_region, kind FROM links WHERE document_id = ?"
        " ORDER BY from_region, to_region, kind",
        (document_id,),
    ):
        links.setdefault(r["from_region"], []).append({"to": r["to_region"], "kind": r["kind"]})

    active = reading_order({i: c["bounds"] for i, c in chunks.items() if c["status"] == "active"})
    orphaned = sorted(i for i, c in chunks.items() if c["status"] != "active")
    order = {cid: n for n, cid in enumerate(active, start=1)}
    out = []
    for cid in active + orphaned:
        c = chunks[cid]
        why = imaging.unreadable_reason(c["bounds"], len(c["element_ids"]))
        if status != "all" and c["status"] != status:
            continue
        if png_stale is not None and c["png_stale"] != png_stale:
            continue
        out.append(
            {
                "id": cid,
                "order": order.get(cid),
                "kind": c["kind"],
                "bounds": c["bounds"],
                "element_ids": c["element_ids"],
                "text": c["text"],
                "latex": c["latex"],
                "source": c["source"],
                "status": c["status"],
                "successor_of": c["successor_of"],
                "png_stale": c["png_stale"],
                "content_hash": c["content_hash"],
                "text_hash": c["text_hash"],
                "links": links.get(cid, []),
                "read_status": "too_large" if why else "ok",
                "read_note": why,
            }
        )
    return {"document": document_id, "version": version, "chunk_count": len(out), "chunks": out}


def chunk_crops(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Active chunks in reading order, with bounds, crop path and png_stale, for the overview."""
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
        raise DocumentNotFound(document_id)
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, bbox, png_path, png_stale FROM regions"
            " WHERE document_id = ? AND created_by = ? AND status = 'active'",
            (document_id, AUTO),
        )
    }
    bounds = {i: json.loads(r["bbox"]) for i, r in rows.items()}
    return [
        {
            "id": cid,
            "bounds": bounds[cid],
            "png_path": rows[cid]["png_path"],
            "png_stale": bool(rows[cid]["png_stale"]),
        }
        for cid in reading_order(bounds)
    ]
