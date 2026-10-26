"""POST /documents/{id}/check_sync (INK-036, decision 0018). Reads only; the recognition worker
is the only writer it may set in motion, and only into the recognition cache."""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from inkbridge import db
from inkbridge.api.deps import Conn
from inkbridge.db import sync

router = APIRouter()

MAX_CHUNKS = 2000
POLL_S = 0.2
Hash = Annotated[str, Field(min_length=1, max_length=128)]


class NoteChunk(BaseModel):
    id: Hash
    hash: Hash  # the chunk's content_hash when the note was written
    reading: Hash | None = None  # the reading's text_hash then (null if it had none)


class CheckSyncIn(BaseModel):
    chunks: Annotated[list[NoteChunk], Field(max_length=MAX_CHUNKS)]
    wait_s: Annotated[float, Field(ge=0, le=30)] = 15.0


@router.post("/documents/{document_id}/check_sync")
async def check_sync(document_id: str, body: CheckSyncIn, conn: Conn, request: Request) -> dict:
    """Per note chunk: fresh, fresh_after_reread, changed, replaced or removed; plus new chunks.

    Chunks whose ink changed and that have no reading yet are handed to the recognition worker,
    and the request waits up to wait_s for their readings (async: no threadpool thread is held
    while waiting). Without a reading a chunk is `changed` with `reading: null`: a visible update,
    never a silent miss.
    """
    notes = [c.model_dump() for c in body.chunks]
    try:
        resolved = await run_in_threadpool(sync.resolve, conn, document_id, notes)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    missing = sync.needs_reading(resolved)
    worker = getattr(request.app.state, "recognition_worker", None)
    if missing and body.wait_s > 0 and worker is not None:
        # Only the ids the worker accepted can arrive (opt-in canvas, not in backoff).
        waiting = list(worker.request(document_id, missing, ttl_s=body.wait_s))
        deadline = time.monotonic() + body.wait_s
        while waiting and time.monotonic() < deadline:
            await asyncio.sleep(max(0.0, min(POLL_S, deadline - time.monotonic())))
            if await run_in_threadpool(sync.has_readings, conn, waiting):
                break
    return await run_in_threadpool(sync.check, conn, document_id, notes)
