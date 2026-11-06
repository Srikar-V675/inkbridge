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
from inkbridge.canvas.raster import render_thumbnail
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


def _store(path: Path, png: bytes, keep_prefix: str) -> None:
    """Write atomically, then drop the other versions of this canvas's thumbnail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(png)
    os.replace(tmp, path)
    for old in path.parent.glob(f"{keep_prefix}*.png"):
        if old != path and old.stem[len(keep_prefix) :].isdigit():  # not another canvas's file
            old.unlink(missing_ok=True)


def _headers(version: int) -> dict[str, str]:
    return {"ETag": f'"v{version}"', "Cache-Control": "no-cache"}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:  # never rendered, or another request just replaced it
        return None


@router.get("/documents/{document_id}/thumbnail")
def thumbnail(document_id: str, conn: Conn, request: Request) -> Response:
    """480x320 PNG of the whole canvas, cached per scene version beside the database."""
    if not _SAFE_ID.fullmatch(document_id):
        raise HTTPException(404, NOT_FOUND)
    try:
        version = db.scene_version(conn, document_id)  # the 304 path never loads the elements
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None
    if request.headers.get("if-none-match") == f'"v{version}"':
        return Response(status_code=304, headers=_headers(version))
    png = _read(config.thumbs_dir() / f"{document_id}-{version}.png")
    if png is None:
        try:
            # The scene may have moved on since the version above: key the file by what is rendered.
            version, raw = db.get_scene(conn, document_id)
        except db.DocumentNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        png = render_thumbnail(json.loads(raw))
        _store(config.thumbs_dir() / f"{document_id}-{version}.png", png, f"{document_id}-")
    return Response(png, media_type="image/png", headers=_headers(version))
