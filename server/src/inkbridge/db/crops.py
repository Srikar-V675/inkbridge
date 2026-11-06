"""Chunk crop images: freshness and reads for the recognition worker."""

import json
import logging
import sqlite3
import uuid
from pathlib import Path

from inkbridge import config, imaging
from inkbridge.canvas import raster

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.documents import get_scene
from inkbridge.db.regions import get_region, get_region_png_path


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


def render_server_crop(conn: sqlite3.Connection, region_id: str) -> bool:
    """Render an active chunk's crop from the stored scene and install it; True if it is now fresh.

    Order matters: scene first, region second, then the version check under the write lock, so a
    save between the two reads shows up as a version mismatch (the crop is dropped, png_stale stays
    set, the next pass retries). Rendering happens outside the lock; saves are never blocked by it.
    Too-large chunks (decision 0052) are never rendered.
    """
    row = conn.execute("SELECT document_id FROM regions WHERE id = ?", (region_id,)).fetchone()
    if row is None:
        return False
    version, elements_json = get_scene(conn, row["document_id"])  # 1. scene
    region = get_region(conn, region_id)  # 2. region (at least as new as the scene)
    if region is None or region["status"] != "active":
        return False
    if imaging.unreadable_reason(region["bounds"], len(region["element_ids"])):
        return False
    by_id = {e["id"]: e for e in json.loads(elements_json) if isinstance(e, dict) and "id" in e}
    png = raster.render_crop([by_id[i] for i in region["element_ids"] if i in by_id])
    if png is None:
        return False
    path = Path(get_region_png_path(conn, region_id))
    tmp = Path(f"{path}.{uuid.uuid4().hex[:8]}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_bytes(png)
        conn.execute("BEGIN IMMEDIATE")  # the lock saves and uploads take
        try:
            if scene_version_of_region(conn, region_id) != version:
                conn.rollback()
                return False
            tmp.replace(path)
            return mark_png_fresh(conn, region_id, version) is not None  # commits; CAS on version
        except BaseException:
            conn.rollback()
            raise
    finally:
        tmp.unlink(missing_ok=True)


def ensure_crop(conn: sqlite3.Connection, region_id: str) -> None:
    """Server mode only: render the crop if the region is png_stale or its file is missing."""
    if config.crop_source() != "server":
        return
    row = conn.execute(
        "SELECT png_stale, png_path FROM regions WHERE id = ? AND status = 'active'", (region_id,)
    ).fetchone()
    if row is None:
        return
    if row["png_stale"] or not row["png_path"] or not Path(row["png_path"]).exists():
        render_server_crop(conn, region_id)
