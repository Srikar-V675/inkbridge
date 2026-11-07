"""Canvases home (INK-118, decision 0069): rename, pin, archive, duplicate, open."""

import json
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from inkbridge import config, db
from inkbridge.api.chunks import NOT_FOUND, DocumentOut, deep_link
from inkbridge.api.deps import Conn
from inkbridge.canvas.raster import THUMB_REVISION, render_thumbnail
from inkbridge.db import outline

router = APIRouter()


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("title must not be blank")
        return v.strip() if v is not None else None

    @model_validator(mode="after")
    def _something(self) -> "DocumentPatch":
        if self.title is None and self.pinned is None and self.archived is None:
            raise ValueError("send at least one of title, pinned, archived")
        return self


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, conn: Conn) -> dict:
    """One canvas's summary (the title for the top bar) without listing them all."""
    try:
        doc = db.document_summary(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    return {**doc, "url": deep_link(doc["id"])}


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def patch_document(document_id: str, body: DocumentPatch, conn: Conn) -> dict:
    try:
        doc = db.patch_document(
            conn, document_id, title=body.title, pinned=body.pinned, archived=body.archived
        )
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    return {**doc, "url": deep_link(doc["id"])}


@router.post("/documents/{document_id}/duplicate", status_code=201, response_model=DocumentOut)
def duplicate_document(document_id: str, conn: Conn) -> dict:
    try:
        doc = outline.duplicate_document(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    except outline.TooManyDocuments:
        raise HTTPException(
            409,
            {
                "code": "too_many_canvases",
                "msg": f"there are already {outline.MAX_DOCUMENTS} canvases; archive or reuse one",
            },
        ) from None
    return {**doc, "url": deep_link(doc["id"])}


@router.post("/documents/{document_id}/open", status_code=204)
def open_document(document_id: str, conn: Conn) -> Response:
    """The web calls this when a canvas view is entered; reads (GET scene, MCP) do not count."""
    try:
        db.mark_opened(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    return Response(status_code=204)


_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Canvas ids hold only [A-Za-z0-9_-], so "." cannot appear in one: "<doc>.r<rev>.<version>.png"
# never collides with another canvas's file, whatever its id ends in. The pre-0070 legacy name
# "<doc>-<version>.png" is still recognised so it can be removed.


def _thumb_path(document_id: str, version: int) -> Path:
    return config.thumbs_dir() / f"{document_id}.r{THUMB_REVISION}.{version}.png"


def _etag(version: int) -> str:
    return f'"r{THUMB_REVISION}v{version}"'


def _store(path: Path, png: bytes, document_id: str) -> None:
    """Write atomically, then drop the other versions, revisions and legacy files of this canvas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(png)
    os.replace(tmp, path)
    own = re.compile(re.escape(document_id) + r"(?:\.r\d+\.\d+|-\d+)\.png")
    for old in path.parent.iterdir():
        if old != path and own.fullmatch(old.name):
            old.unlink(missing_ok=True)


def _headers(version: int) -> dict[str, str]:
    return {"ETag": _etag(version), "Cache-Control": "no-cache"}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:  # never rendered, or another request just replaced it
        return None


@router.get("/documents/{document_id}/thumbnail")
def thumbnail(document_id: str, conn: Conn, request: Request) -> Response:
    """960x640 PNG of the centre chunk of the canvas, cached per scene version beside the database."""
    if not _SAFE_ID.fullmatch(document_id):
        raise HTTPException(404, NOT_FOUND)
    try:
        version = db.scene_version(conn, document_id)  # the 304 path never loads the elements
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    if request.headers.get("if-none-match") == _etag(version):
        return Response(status_code=304, headers=_headers(version))
    png = _read(_thumb_path(document_id, version))
    if png is None:
        try:
            # The scene may have moved on since the version above: key the file by what is rendered.
            version, raw = db.get_scene(conn, document_id)
        except db.DocumentNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        png = render_thumbnail(json.loads(raw), chunks=db.active_chunk_bounds(conn, document_id))
        _store(_thumb_path(document_id, version), png, document_id)
    return Response(png, media_type="image/png", headers=_headers(version))
