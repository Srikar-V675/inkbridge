import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile

from inkbridge import config, db, imaging
from inkbridge.api.deps import Conn

router = APIRouter()


def _crops_dir() -> Path:
    return config.db_path().parent / "crops"


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
    png = await image.read()
    if not imaging.is_valid_png(png):
        raise HTTPException(422, "image must be a PNG")

    rid = uuid.uuid4().hex[:12]
    path = _crops_dir() / f"{rid}.png"
    try:
        region = db.create_region(
            conn, document_id, ids, str(path), kind=kind, created_by=created_by, region_id=rid
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.UnknownElements as e:
        raise HTTPException(422, f"unknown element ids: {e.ids}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return region


@router.get("/documents/{document_id}/regions")
def list_regions(document_id: str, conn: Conn, kind: str | None = None, limit: int = 100):
    return db.list_regions(conn, document_id, kind=kind, limit=limit)


@router.get("/regions/{region_id}")
def get_region(region_id: str, conn: Conn) -> dict:
    region = db.get_region(conn, region_id)
    if region is None:
        raise HTTPException(404, "region not found")
    return region


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
