"""Canvases and the chunk outline (INK-033): what read_canvas and the export skill read."""

import json
import sqlite3
import uuid

from inkbridge.chunker import reading_order
from inkbridge.db import AUTO, DocumentNotFound, _now, _region_dict

STATUSES = ("active", "orphaned", "all")


def create_document(conn: sqlite3.Connection, title: str) -> dict:
    """A new, empty canvas (scene at version 0) with a fresh 12-hex id."""
    doc_id, now = uuid.uuid4().hex[:12], _now()
    conn.execute(
        "INSERT INTO documents (id, title, updated_at) VALUES (?, ?, ?)", (doc_id, title, now)
    )
    conn.execute(
        "INSERT INTO scenes (document_id, version, elements_json, updated_at) VALUES (?, 0, '[]', ?)",
        (doc_id, now),
    )
    conn.commit()
    return {"id": doc_id, "title": title, "updated_at": now, "version": 0}


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    """Every canvas, most recently updated first."""
    return [
        {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"], "version": r["version"]}
        for r in conn.execute(
            "SELECT d.id, d.title, d.updated_at, s.version FROM documents d"
            " LEFT JOIN scenes s ON s.document_id = d.id ORDER BY d.updated_at DESC, d.id"
        )
    ]


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
        "SELECT from_region, to_region, kind FROM links WHERE document_id = ?"
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
            }
        )
    return {"document": document_id, "version": version, "chunk_count": len(out), "chunks": out}


def chunk_crops(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Active chunks with bounds, crop path and png_stale, for the overview composite."""
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
        raise DocumentNotFound(document_id)
    return [
        {
            "id": r["id"],
            "bounds": json.loads(r["bbox"]),
            "png_path": r["png_path"],
            "png_stale": bool(r["png_stale"]),
        }
        for r in conn.execute(
            "SELECT id, bbox, png_path, png_stale FROM regions"
            " WHERE document_id = ? AND created_by = ? AND status = 'active' ORDER BY id",
            (document_id, AUTO),
        )
    ]
