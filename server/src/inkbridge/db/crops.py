"""Chunk crop images: freshness and reads for the recognition worker."""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.regions import get_region


def scene_version_of_region(conn: sqlite3.Connection, region_id: str) -> int | None:
    """Current scene version of the region's document; None if the region is unknown."""
    row = conn.execute(
        "SELECT s.version FROM regions r JOIN scenes s ON s.document_id = r.document_id"
        " WHERE r.id = ?",
        (region_id,),
    ).fetchone()
    return row["version"] if row else None


def mark_png_fresh(
    conn: sqlite3.Connection, region_id: str, scene_version: int | None = None
) -> dict | None:
    """Clear png_stale after the client has saved a new crop; None if nothing was cleared.

    With scene_version the clear is a compare-and-set against the document's scene version, in
    one statement: a save that lands after the crop was rendered (even after its file was
    written) leaves the flag set, so a crop of older ink is never reported fresh (INK-057).
    """
    sql = "UPDATE regions SET png_stale = 0 WHERE id = ?"
    args: list = [region_id]
    if scene_version is not None:
        sql += " AND (SELECT version FROM scenes WHERE document_id = regions.document_id) = ?"
        args.append(scene_version)
    cur = conn.execute(sql, args)
    conn.commit()
    return get_region(conn, region_id) if cur.rowcount else None


def stale_crop_ids(conn: sqlite3.Connection, document_id: str) -> list[str]:
    """Active regions whose crop no longer matches their ink (the browser re-exports them)."""
    rows = conn.execute(
        "SELECT id FROM regions WHERE document_id = ? AND status = 'active' AND png_stale = 1"
        " ORDER BY id",
        (document_id,),
    )
    return [r["id"] for r in rows]


def read_fresh_crop(conn: sqlite3.Connection, region_id: str, content_hash_: str) -> bytes | None:
    """The crop's bytes if the region is still active with this content_hash and a fresh crop.

    Read under BEGIN IMMEDIATE, the lock crop uploads take while they rename and clear png_stale,
    so the bytes always show the ink of content_hash_ (INK-014). None otherwise or if no file.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT png_path FROM regions WHERE id = ? AND status = 'active' AND png_stale = 0"
            " AND content_hash = ?",
            (region_id, content_hash_),
        ).fetchone()
        if row is None:
            return None
        try:
            return Path(row["png_path"]).read_bytes()
        except OSError:
            return None  # no crop file yet: nothing to read until the browser saves one
    finally:
        conn.rollback()  # read-only: release the lock
