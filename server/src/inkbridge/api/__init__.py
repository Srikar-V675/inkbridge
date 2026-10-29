import json
import math
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from inkbridge import db
from inkbridge.api import chunks, ops, regions, search, sync, ws
from inkbridge.api.deps import Conn
from inkbridge.api.limits import BodySizeLimit
from inkbridge.recognition_worker import RecognitionWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Off unless INKBRIDGE_RECOGNIZE_DOCUMENTS lists test canvases (decision 0017).
    worker = RecognitionWorker.from_env(publish=ws.hub.publish)
    if worker is not None:
        worker.start()
    app.state.recognition_worker = worker  # check_sync asks it for readings (INK-036)
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


app = FastAPI(title="Inkbridge", lifespan=lifespan)
app.add_middleware(BodySizeLimit)  # 413 before any route reads an oversized body


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # The default body echoes the offending input, which cannot be encoded when it holds NaN.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


app.include_router(chunks.router)
app.include_router(ops.router)
app.include_router(regions.router)
app.include_router(search.router)
app.include_router(sync.router)
app.include_router(ws.router)


MAX_ELEMENTS = 50_000
_NUMERIC_FIELDS = ("x", "y", "width", "height", "angle")


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _all_finite(v: Any) -> bool:
    """False if any float anywhere inside v is NaN or infinite (JSON would store it as null)."""
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, dict):
        return all(_all_finite(x) for x in v.values())
    if isinstance(v, list):
        return all(_all_finite(x) for x in v)
    return True


def _check_geometry(el: dict[str, Any]) -> None:
    """Reject shapes that bbox_of / the stroke hash would crash on (they would wedge autosave)."""
    for f in _NUMERIC_FIELDS:
        if f in el and not _is_number(el[f]):
            raise ValueError(f"element {el['id']!r}: {f} must be a finite number")
    pts = el.get("points")
    if pts is not None and not (
        isinstance(pts, list)
        and all(isinstance(p, list) and len(p) >= 2 and all(_is_number(c) for c in p) for p in pts)
    ):
        raise ValueError(f"element {el['id']!r}: points must be a list of [x, y] numbers")
    pressures = el.get("pressures")
    if pressures is not None and not (
        isinstance(pressures, list) and all(_is_number(c) for c in pressures)
    ):
        raise ValueError(f"element {el['id']!r}: pressures must be a list of numbers")


class SceneIn(BaseModel):
    base_version: int = Field(ge=0)
    elements: list[dict[str, Any]]

    @field_validator("elements")
    @classmethod
    def _elements_valid(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(v) > MAX_ELEMENTS:
            raise ValueError(f"too many elements (max {MAX_ELEMENTS})")
        if not all(isinstance(e.get("id"), str) for e in v):
            raise ValueError("every element needs a string id")
        if not all(_all_finite(e) for e in v):
            raise ValueError("NaN and Infinity are not allowed")
        for e in v:
            _check_geometry(e)
        return v


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/documents/{document_id}/scene")
def get_scene(document_id: str, conn: Conn) -> dict[str, Any]:
    try:
        version, elements_json = db.get_scene(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    return {"version": version, "elements": json.loads(elements_json)}


@app.put("/documents/{document_id}/scene")
def put_scene(document_id: str, body: SceneIn, conn: Conn) -> dict[str, int]:
    try:
        version = db.put_scene(
            conn,
            document_id,
            body.base_version,
            json.dumps(body.elements, ensure_ascii=False, separators=(",", ":")),
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.VersionConflict as e:
        raise HTTPException(409, {"current_version": e.current_version}) from None
    ws.hub.publish(
        document_id,
        {
            "type": "chunks.updated",
            "version": version,
            "stale_crops": db.stale_crop_ids(conn, document_id),
        },
    )
    return {"version": version}
