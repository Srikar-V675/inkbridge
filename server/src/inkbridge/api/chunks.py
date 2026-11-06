"""Canvases, the chunk outline, the overview composite and full-size crops (INK-033)."""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from inkbridge import config, db, imaging
from inkbridge.api.deps import Conn
from inkbridge.db import outline, sync

router = APIRouter()


class Out(BaseModel):
    """Response base. extra="allow": a field added to a db dict later is still served, never
    silently dropped. Declared fields have no defaults, so no key appears or disappears."""

    model_config = ConfigDict(extra="allow")


class Link(Out):
    to: str
    kind: str


class ChunkOut(Out):
    id: str
    order: int | None
    kind: str | None
    bounds: dict[str, float]
    element_ids: list[str]
    text: str | None
    latex: str | None
    source: str | None
    status: str
    successor_of: str | None
    png_stale: bool
    content_hash: str | None
    text_hash: str | None
    links: list[Link]
    read_status: str
    read_note: str | None
    deep_link: str


class ChunkOutline(Out):
    document: str
    version: int
    chunk_count: int
    chunks: list[ChunkOut]


class DocumentOut(Out):
    id: str
    title: str
    updated_at: str
    version: int
    url: str
    pinned: bool
    archived: bool
    element_count: int
    chunk_count: int
    open_offers: int
    last_opened_at: str | None


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


@router.post("/documents", status_code=201, response_model=DocumentOut)
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


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(conn: Conn, archived: Literal["true", "false", "all"] = "false") -> list[dict]:
    """Canvases, newest edit first. Archived ones are hidden unless ?archived=true or all."""
    return [{**d, "url": deep_link(d["id"])} for d in db.list_documents(conn, archived)]


@router.get("/documents/{document_id}/chunks", response_model=ChunkOutline)
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


MAX_RENDER_PER_OVERVIEW = 24  # server-mode crops rendered inside one overview request


@router.get("/documents/{document_id}/overview")
def get_overview(
    document_id: str,
    conn: Conn,
    max_width: Annotated[int, Query(ge=64, le=4096)] = imaging.MAX_IMAGE_WIDTH,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    """One band of active chunk crops, in reading order from chunk index `offset`.

    A spread-out canvas is split into bands (see imaging.plan_bands) so each box stays readable.
    Headers: X-Overview-From (offset), X-Overview-Count (chunks drawn), X-Overview-Total (active
    chunks), and X-Overview-Next (the offset of the following band; absent on the last one).
    """
    try:
        chunks = outline.chunk_crops(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    bands = imaging.plan_bands(chunks[offset:], max_width)
    band = bands[0] if bands else []
    if config.crop_source() == "server":  # render what is stale, a few per call (INK-120)
        stale = [c for c in band if c["png_stale"]][:MAX_RENDER_PER_OVERVIEW]
        for c in stale:
            if db.render_server_crop(conn, c["id"]):
                c["png_stale"] = False  # the rest stay framed; a later call finishes them
    paths = {c["id"]: Path(c.pop("png_path") or "") for c in band}

    def load(chunk_id: str) -> bytes | None:
        path = paths[chunk_id]
        return path.read_bytes() if path.is_file() else None

    headers = {
        "X-Overview-From": str(offset),
        "X-Overview-Count": str(len(band)),
        "X-Overview-Total": str(len(chunks)),
    }
    if len(bands) > 1:
        headers["X-Overview-Next"] = str(offset + len(band))
    return Response(
        imaging.overview(band, load, max_width), media_type="image/png", headers=headers
    )


def refuse_orphan(conn, region_id: str, history: bool) -> None:
    """Orphaned chunks hold stale ink; point the caller at the live chunk (INK-084)."""
    region = db.get_region(conn, region_id)
    if region is None or history or region["status"] == "active":
        return
    live = sync._live_successor(conn, region, region["document_id"])
    raise HTTPException(
        410,
        f"chunk {region_id} was replaced or deleted; "
        + (f"read live_successor {live['id']}" if live else "call read_canvas")
        + " (or pass ?history=true for the old ink)",
    )


@router.get("/regions/{region_id}/png")
def get_region_png(region_id: str, conn: Conn, history: bool = False) -> Response:
    """The stored crop byte for byte (full size); /image is the downscaled one."""
    refuse_orphan(conn, region_id, history)
    db.ensure_crop(conn, region_id)  # server mode: render a stale or missing crop (INK-120)
    path = db.get_region_png_path(conn, region_id)
    if path is None:
        raise HTTPException(404, "region not found; GET /documents/{id}/chunks lists chunk ids")
    if not Path(path).is_file():
        raise HTTPException(404, "no crop stored yet for this region (png_stale until uploaded)")
    return Response(Path(path).read_bytes(), media_type="image/png")
