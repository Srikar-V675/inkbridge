import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from inkbridge import config, db, imaging
from inkbridge.api.deps import Conn

router = APIRouter()


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _read_png(image: UploadFile) -> bytes:
    png = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(png) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "image too large (10 MB max)")
    if not imaging.is_valid_png(png):
        raise HTTPException(422, "image must be a PNG")
    return png


@router.post("/documents/{document_id}/regions", status_code=201)
async def create_region(
    document_id: str,
    conn: Conn,
    element_ids: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
    kind: Annotated[str | None, Form()] = None,
    created_by: Annotated[str, Form()] = "user",
) -> dict:
    try:
        ids = json.loads(element_ids)
    except json.JSONDecodeError:
        raise HTTPException(422, "element_ids must be a JSON list") from None
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise HTTPException(422, "element_ids must be a non-empty list of strings")
    ids = list(dict.fromkeys(ids))
    png = await _read_png(image)
    # File and SQLite work block (BEGIN IMMEDIATE can wait on a scene write), so keep it off the loop.
    return await run_in_threadpool(_store_region, conn, document_id, ids, png, kind, created_by)


def _store_region(conn, document_id, ids, png, kind, created_by) -> dict:
    rid = uuid.uuid4().hex[:12]
    path = config.crops_dir() / f"{rid}.png"
    # File first: a region row must never exist without its crop.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    try:
        return db.create_region(
            conn, document_id, ids, str(path), kind=kind, created_by=created_by, region_id=rid
        )
    except db.DocumentNotFound:
        path.unlink(missing_ok=True)
        raise HTTPException(404, "document not found") from None
    except db.UnknownElements as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"unknown element ids: {e.ids}") from None
    except db.ReservedCreator:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "created_by 'auto' is reserved for chunks") from None
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@router.get("/documents/{document_id}/regions")
def list_regions(
    document_id: str,
    conn: Conn,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    chunks: bool = False,
    png_stale: bool | None = None,
):
    """Manual regions; ?chunks=true lists the auto chunks instead (INK-033 adds reading order).

    ?png_stale=true lists only regions whose crop must be rendered again (browser crop sync).
    """
    if not db.document_exists(conn, document_id):
        raise HTTPException(404, "document not found")
    return db.list_regions(
        conn, document_id, kind=kind, limit=limit, chunks=chunks, png_stale=png_stale
    )


@router.get("/regions/{region_id}")
def get_region(region_id: str, conn: Conn) -> dict:
    region = db.get_region(conn, region_id)
    if region is None:
        raise HTTPException(404, "region not found")
    return region


@router.put("/regions/{region_id}/image")
async def replace_region_image(
    region_id: str,
    conn: Conn,
    image: Annotated[UploadFile, File()],
    scene_version: Annotated[int | None, Form()] = None,
) -> dict:
    """Store a fresh crop (after the client re-exports the region) and clear png_stale.

    scene_version is the scene the browser rendered the crop from. If the scene has moved on, the
    crop may show older ink: 409 with current_version and nothing is written (decision 0012).
    """
    png = await _read_png(image)
    return await run_in_threadpool(_replace_image, conn, region_id, png, scene_version)


def _version_conflict(current: int | None) -> HTTPException:
    return HTTPException(409, {"current_version": current})


def _replace_image(conn, region_id: str, png: bytes, scene_version: int | None) -> dict:
    path = db.get_region_png_path(conn, region_id)
    if path is None:
        raise HTTPException(404, "region not found")
    if scene_version is not None:
        current = db.scene_version_of_region(conn, region_id)
        if current != scene_version:
            raise _version_conflict(current)
    # A temp name of its own, so two uploads of the same crop never write into one file.
    tmp = Path(f"{path}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)  # a chunk's first crop creates the folder
    try:
        tmp.write_bytes(png)
        tmp.replace(path)  # atomic: a crash mid-write never leaves a half-written crop
    finally:
        tmp.unlink(missing_ok=True)
    region = db.mark_png_fresh(conn, region_id, scene_version)
    if region is not None:
        return region
    if db.get_region_png_path(conn, region_id) is None:
        raise HTTPException(404, "region not found")
    # A save landed after the check: the new file stays, but it is still flagged stale.
    raise _version_conflict(db.scene_version_of_region(conn, region_id))


@router.get("/regions/{region_id}/image")
def get_region_image(
    region_id: str,
    conn: Conn,
    max_width: Annotated[int, Query(ge=1, le=8192)] = imaging.MAX_IMAGE_WIDTH,
) -> Response:
    """The crop, downscaled to max_width (default 1024). The stored file is never modified."""
    path = db.get_region_png_path(conn, region_id)
    if path is None or not Path(path).exists():
        raise HTTPException(404, "image not found")
    return Response(imaging.cap_width(Path(path).read_bytes(), max_width), media_type="image/png")


@router.get("/regions/{region_id}/ink")
def get_region_ink(
    region_id: str,
    conn: Conn,
    max_points: Annotated[int, Query(ge=2, le=100_000)] = imaging.MAX_INK_POINTS,
) -> dict:
    ink = db.get_region_ink(conn, region_id)
    if ink is None:
        raise HTTPException(404, "region not found")
    strokes = imaging.decimate_strokes(ink["strokes"], max_points)
    count = sum(len(s["points"]) for s in strokes)
    return {
        "strokes": strokes,
        "point_count": count,
        "original_point_count": ink["point_count"],
        "decimated": count < ink["point_count"],
    }
