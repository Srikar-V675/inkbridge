import asyncio
import logging
import math
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
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
    markup,
    memory,
    offers,
    ops,
    overrides,
    questions,
    regions,
    retrieve,
    search,
    sync,
    tasks,
    watch,
    ws,
)
from inkbridge.api.deps import Conn
from inkbridge.api.limits import BodySizeLimit
from inkbridge.api.web import mount_web
from inkbridge.db import questions as q_db
from inkbridge.db import tasks as tasks_db
from inkbridge.recognizer.worker import RecognitionWorker
from inkbridge.timing import RequestTiming, configure_logging, request_parts, sample_loop_lag


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    lag = asyncio.create_task(sample_loop_lag())
    db.init_db()
    # Off unless INKBRIDGE_RECOGNIZE_DOCUMENTS lists test canvases (decision 0017).
    worker = RecognitionWorker.from_env(publish=offers.publish_chunks)
    if worker is not None:
        worker.start()
    app.state.recognition_worker = worker  # check_sync asks it for readings (INK-036)
    ask, ask_error = AskWorker.setup(publish=ws.hub.publish)  # off unless INKBRIDGE_RUNNER is set
    app.state.runner_error = ask_error  # set when INKBRIDGE_RUNNER is on but refused (INK-103)
    conn = db.connect()
    try:
        q_db.reset_runner(conn, "failed" if ask_error else "pending", ask_error)
        tasks_db.reset_runner(conn)
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
app.include_router(markup.router)
app.include_router(offers.router)
app.include_router(ops.router)
app.include_router(overrides.router)
app.include_router(questions.router)
app.include_router(regions.router)
app.include_router(retrieve.router)
app.include_router(search.router)
app.include_router(sync.router)
app.include_router(tasks.router)
app.include_router(watch.router)
app.include_router(memory.router)
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


def _check_elements(v: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The checks every element list gets, whichever route it arrives on."""
    if len(v) > MAX_ELEMENTS:
        raise ValueError(f"too many elements (max {MAX_ELEMENTS})")
    if not all(isinstance(e.get("id"), str) for e in v):
        raise ValueError("every element needs a string id")
    if not all(_all_finite(e) for e in v):
        raise ValueError("NaN and Infinity are not allowed")
    for e in v:
        _check_geometry(e)
    return v


class SceneIn(BaseModel):
    base_version: int = Field(ge=0)  # kept so old tabs validate; it no longer locks (decision 0080)
    elements: list[dict[str, Any]]
    delta: bool = False  # accepted and ignored: a full list and a delta are the same merge

    @field_validator("elements")
    @classmethod
    def _elements_valid(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _check_elements(v)


class ElementsIn(BaseModel):
    device: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    batch: int = Field(ge=0)
    elements: list[dict[str, Any]]

    @field_validator("elements")
    @classmethod
    def _elements_valid(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _check_elements(v)


@app.get("/health")
def health() -> dict[str, str]:
    # `chunker` is the default for canvases with no setting of their own; a canvas's own value is
    # in `GET /documents`.
    return {"status": "ok", "crop_source": config.crop_source(), "chunker": config.chunker()}


@app.get("/documents/{document_id}/scene")
def get_scene(document_id: str, conn: Conn, deleted: bool = False) -> Response:
    """The live elements (INK-110); `?deleted=true` adds deleted ones, for the 409 reload."""
    t0 = time.perf_counter()
    try:
        seq, array, count = db.get_live_scene(conn, document_id, include_deleted=deleted)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    # The stored row text goes out as is: no decode/encode round trip (INK-080).
    # `version` is an alias of `seq` until the web client moves to `seq` (INK-111).
    body = f'{{"seq":{seq},"version":{seq},"elements":{array}}}'
    _scene_log.info(
        "scene GET doc=%s seq=%d elements=%d bytes=%d ms=%.1f",
        document_id,
        seq,
        count,
        len(body.encode()),
        (time.perf_counter() - t0) * 1000,
    )
    return Response(body, media_type="application/json")


@app.get("/documents/{document_id}/elements")
def get_elements(document_id: str, conn: Conn, since: Annotated[int, Query(ge=0)]) -> Response:
    """Every element row written after `since`, deleted rows and tombstone stubs included."""
    try:
        seq, array, _ = db.scene_changes(conn, document_id, since)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    return Response(f'{{"seq":{seq},"elements":{array}}}', media_type="application/json")


_log = logging.getLogger("inkbridge.request")
_scene_log = logging.getLogger("inkbridge.scene")


@app.post("/documents/{document_id}/elements")
def post_elements(
    document_id: str, body: ElementsIn, conn: Conn, request: Request
) -> dict[str, Any]:
    """Merge a batch of elements (INK-111, decision 0080). N1: drafts and new `<op_id>:` ids are refused."""
    timing = request_parts(request.scope, time.perf_counter())
    try:
        r = db.merge_elements(
            conn,
            document_id,
            body.elements,
            key=f"{body.device}:{body.batch}",
            strict=True,
            max_elements=MAX_ELEMENTS,
            timings=timing,
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.ElementsRefused as e:
        raise HTTPException(
            422,
            {"refused": e.ids, "reason": "drafts and op-prefixed new ids are not accepted"},
        ) from None
    except db.SceneTooLarge:
        raise HTTPException(422, f"too many elements (max {MAX_ELEMENTS})") from None
    _publish_if_changed(conn, document_id, r, body.device)
    return {"seq": r.seq, "newer": r.newer, "timing": timing}


def _publish_if_changed(conn, document_id: str, r: db.MergeResult, origin: str) -> None:
    if r.replay or not r.changed:
        return
    shown = [
        e
        for e in r.written
        if not (isinstance(e.get("customData"), dict) and e["customData"].get("draft"))
    ]
    if shown:  # first, so a tab applies the ink before it hears about stale crops
        ws.hub.publish(
            document_id,
            {"type": "scene.delta", "seq": r.seq, "origin": origin, "elements": shown},
        )
    ws.hub.publish(
        document_id,
        {
            "type": "chunks.updated",
            "version": r.seq,
            "stale_crops": db.stale_crop_ids(conn, document_id),
        },
    )
    offers.schedule_scan(document_id)


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
        # strict=False: INK-114 drops this flag (the legacy PUT keeps storing drafts until drafts leave the scene)
        r = db.merge_elements(
            conn,
            document_id,
            body.elements,
            key=key,
            base_seq=body.base_version,
            strict=False,
            max_elements=MAX_ELEMENTS,
            timings=timing,
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.SceneTooLarge:
        raise HTTPException(422, f"too many elements (max {MAX_ELEMENTS})") from None
    _publish_if_changed(conn, document_id, r, tab if key else "")
    return {"version": r.seq, "seq": r.seq, "newer": r.newer, "timing": timing}


mount_web(app, config.web_dist())  # last: every API route wins over the static paths (INK-100)
