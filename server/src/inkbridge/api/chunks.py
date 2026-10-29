"""Canvases, the chunk outline, the overview composite and full-size crops (INK-033)."""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from inkbridge import config, db, imaging
from inkbridge.api.deps import Conn
from inkbridge.db import outline

router = APIRouter()

NOT_FOUND = "document not found; GET /documents lists the canvases"


def deep_link(document_id: str, chunk_id: str | None = None) -> str:
    url = f"{config.public_url()}/?canvas={quote(document_id, safe='')}"
    return url + (f"&chunk={quote(chunk_id, safe='')}" if chunk_id else "")


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


@router.post("/documents", status_code=201)
def create_document(body: DocumentIn, conn: Conn) -> dict:
    try:
        doc = outline.create_document(conn, body.title)
    except outline.TooManyDocuments:
        raise HTTPException(
            409,
            {
                "code": "too_many_canvases",
                "msg": f"there are already {outline.MAX_DOCUMENTS} canvases; "
                "write into an existing one (pass its document_id)",
            },
        ) from None
    return {**doc, "url": deep_link(doc["id"])}


@router.get("/documents")
def list_documents(conn: Conn) -> list[dict]:
    return [{**d, "url": deep_link(d["id"])} for d in outline.list_documents(conn)]


@router.get("/documents/{document_id}/chunks")
def list_chunks(
    document_id: str,
    conn: Conn,
    status: Literal["active", "orphaned", "all"] = "active",
    png_stale: bool | None = None,
) -> dict:
    """Chunks in reading order; ?png_stale=1 lists the ones whose crop needs re-exporting."""
    try:
        result = outline.chunk_outline(conn, document_id, status=status, png_stale=png_stale)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    for c in result["chunks"]:
        c["deep_link"] = deep_link(document_id, c["id"])
    return result


@router.get("/documents/{document_id}/overview")
def get_overview(
    document_id: str,
    conn: Conn,
    max_width: Annotated[int, Query(ge=64, le=4096)] = imaging.MAX_IMAGE_WIDTH,
) -> Response:
    """All active chunk crops placed at their bounds with ids; boxes where a crop is missing."""
    try:
        chunks = outline.chunk_crops(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    paths = {c["id"]: Path(c.pop("png_path") or "") for c in chunks}

    def load(chunk_id: str) -> bytes | None:
        path = paths[chunk_id]
        return path.read_bytes() if path.is_file() else None

    return Response(imaging.overview(chunks, load, max_width), media_type="image/png")


@router.get("/regions/{region_id}/png")
def get_region_png(region_id: str, conn: Conn) -> Response:
    """The stored crop byte for byte (full size); /image is the downscaled one."""
    path = db.get_region_png_path(conn, region_id)
    if path is None:
        raise HTTPException(404, "region not found; GET /documents/{id}/chunks lists chunk ids")
    if not Path(path).is_file():
        raise HTTPException(404, "no crop stored yet for this region (png_stale until uploaded)")
    return Response(Path(path).read_bytes(), media_type="image/png")
