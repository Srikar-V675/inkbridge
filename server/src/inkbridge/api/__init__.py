import asyncio
import json
import logging
import math
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.gzip import GZipMiddleware

from inkbridge import config, db
from inkbridge.agent.ask_runner import AskWorker
from inkbridge.api import (
    canvases,
    chunks,
    debug,
    graph,
    ops,
    overrides,
    questions,
    regions,
    search,
    sync,
    ws,
)
from inkbridge.api.deps import Conn
from inkbridge.api.limits import BodySizeLimit
from inkbridge.api.web import mount_web
from inkbridge.db import questions as q_db
from inkbridge.recognizer.worker import RecognitionWorker
from inkbridge.timing import RequestTiming, configure_logging, request_parts, sample_loop_lag


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    lag = asyncio.create_task(sample_loop_lag())
    db.init_db()
    # Off unless INKBRIDGE_RECOGNIZE_DOCUMENTS lists test canvases (decision 0017).
    worker = RecognitionWorker.from_env(publish=ws.hub.publish)
    if worker is not None:
        worker.start()
    app.state.recognition_worker = worker  # check_sync asks it for readings (INK-036)
    ask, ask_error = AskWorker.setup(publish=ws.hub.publish)  # off unless INKBRIDGE_RUNNER is set
    app.state.runner_error = ask_error  # set when INKBRIDGE_RUNNER is on but refused (INK-103)
    conn = db.connect()
    try:
        q_db.reset_runner(conn, "failed" if ask_error else "pending", ask_error)
    finally:
        conn.close()
    if ask:
        ask.start()
    app.state.ask_worker = ask
    try:
        yield
    finally:
        lag.cancel()
        try:
            if worker is not None:
                worker.stop()
        finally:
            if ask:
                ask.stop()


app = FastAPI(title="Inkbridge", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=3)  # INK-080 (decision 0055)
app.add_middleware(BodySizeLimit)  # 413 before any route reads an oversized body
app.add_middleware(RequestTiming)  # added last = outermost: times the body-limit 413 too


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # The default body echoes the offending input, which cannot be encoded when it holds NaN.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


app.include_router(canvases.router)
app.include_router(chunks.router)
app.include_router(graph.router)
app.include_router(ops.router)
app.include_router(overrides.router)
app.include_router(questions.router)
app.include_router(regions.router)
app.include_router(search.router)
app.include_router(sync.router)
app.include_router(ws.router)
if debug.enabled():  # absent unless INKBRIDGE_DEVICE_LOG=1 (INK-102)
    app.include_router(debug.router)


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
    delta: bool = False  # elements are only those changed since base_version (INK-075)

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
    return {"status": "ok", "crop_source": config.crop_source()}


@app.get("/documents/{document_id}/scene")
def get_scene(document_id: str, conn: Conn) -> Response:
    try:
        version, elements_json = db.get_scene(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    # The stored text goes out as is: no decode/encode round trip (INK-080).
    return Response(
        f'{{"version":{version},"elements":{elements_json}}}', media_type="application/json"
    )


_last_writer: dict[str, tuple[str, str]] = {}  # document -> (tab, ip) of the last save (INK-083)
_log = logging.getLogger("inkbridge.request")


@app.put("/documents/{document_id}/scene")
def put_scene(
    document_id: str,
    body: SceneIn,
    conn: Conn,
    request: Request,
    x_inkbridge_save: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    timing = request_parts(request.scope, time.perf_counter())
    key = (
        x_inkbridge_save
        if re.fullmatch(r"[a-z0-9]{1,16}:\d{1,9}", x_inkbridge_save or "")
        else None
    )
    tab = key.split(":")[0] if key else "?"
    replay = key is not None and db.was_applied(document_id, key)
    ip = request.client.host if request.client else "?"
    _log.info(
        "scene PUT doc=%s tab=%s ip=%s ua=%s key=%s",
        document_id,
        tab,
        ip,
        request.headers.get("user-agent", "?"),
        x_inkbridge_save,
    )
    try:
        version = db.put_scene(
            conn,
            document_id,
            body.base_version,
            json.dumps(body.elements, ensure_ascii=False, separators=(",", ":")),
            delta=body.delta,
            max_elements=MAX_ELEMENTS,
            save_key=key,
            timings=timing,
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.VersionConflict as e:
        detail: dict[str, Any] = {"current_version": e.current_version}
        if last := _last_writer.get(document_id):
            detail["last_writer"] = {"tab": last[0], "same_ip": last[1] == ip}
        raise HTTPException(409, detail) from None
    except db.SceneTooLarge:
        raise HTTPException(422, f"too many elements (max {MAX_ELEMENTS})") from None
    if replay:
        return {"version": version, "timing": timing}
    if key:
        _last_writer[document_id] = (tab, ip)
    ws.hub.publish(
        document_id,
        {
            "type": "chunks.updated",
            "version": version,
            "stale_crops": db.stale_crop_ids(conn, document_id),
        },
    )
    return {"version": version, "timing": timing}


mount_web(app, config.web_dist())  # last: every API route wins over the static paths (INK-100)
