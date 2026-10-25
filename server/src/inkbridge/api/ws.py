"""WebSocket push channel (INK-042, tech ref 7.3): `WS /ws?document={id}`.

server -> browser: `op.pending {op_id, type, payload}`, `op.updated {op_id, status, error}`,
`op.error {op_id, code, detail}` (a refused ack), `chunks.updated {version, stale_crops}`,
`question.update {question}` (INK-047). browser -> server: `op.applied {op_id, element_ids}`,
`op.failed {op_id, error}`.

On every connect the server replays all pending and delivered ops for the document; an op is
marked delivered once one browser got it. Ops are idempotent by op_id: the browser checks for
elements it already drew for that op before drawing again.

HTTP routes run in the threadpool, so they publish through `hub.publish`, which hands the send
to the event loop that owns the sockets.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from inkbridge import db
from inkbridge.db import ops as ops_db

router = APIRouter()
log = logging.getLogger(__name__)

REPLAY_STATUSES = ["pending", "delivered"]


def _pending_message(op: dict) -> dict:
    return {
        "type": "op.pending",
        "op_id": op["id"],
        "op_type": op["type"],
        "payload": op["payload"],
    }


def updated_message(op: dict) -> dict:
    return {"type": "op.updated", "op_id": op["id"], "status": op["status"], "error": op["error"]}


def _with_conn(fn, *args):
    conn = db.connect()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def join(self, document_id: str, ws: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        self._sockets.setdefault(document_id, set()).add(ws)

    def leave(self, document_id: str, ws: WebSocket) -> None:
        self._sockets.get(document_id, set()).discard(ws)

    def connected(self, document_id: str) -> int:
        return len(self._sockets.get(document_id, ()))

    async def send(self, document_id: str, message: dict) -> int:
        """Send to every socket of the document; return how many got it."""
        sent = 0
        for ws in list(self._sockets.get(document_id, ())):
            try:
                await ws.send_json(message)
                sent += 1
            except (WebSocketDisconnect, RuntimeError, OSError):  # socket went away mid-send
                self.leave(document_id, ws)
        return sent

    async def push_op(self, document_id: str, op_id: str) -> None:
        # Re-read: a PATCH (failed, expired) may have landed since the op was queued.
        op = await run_in_threadpool(_with_conn, ops_db.get_op, op_id)
        if op["status"] not in REPLAY_STATUSES:
            return
        if await self.send(document_id, _pending_message(op)):
            await run_in_threadpool(_with_conn, ops_db.mark_delivered, op_id)

    def publish(self, document_id: str, message: dict | None = None, op: dict | None = None):
        """Thread-safe, fire and forget. With `op`, push it as op.pending (and mark delivered)."""
        loop = self._loop
        if loop is None or loop.is_closed() or not self.connected(document_id):
            return
        coro = self.push_op(document_id, op["id"]) if op else self.send(document_id, message or {})
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.add_done_callback(_log_failure)


def _log_failure(future) -> None:
    if not future.cancelled() and future.exception() is not None:
        log.error("websocket publish failed", exc_info=future.exception())


hub = Hub()


async def _handle(ws: WebSocket, document_id: str, msg: Any) -> None:
    if not isinstance(msg, dict) or not isinstance(msg.get("op_id"), str):
        await ws.send_json({"type": "error", "detail": "expected {type, op_id, ...}"})
        return
    op_id = msg["op_id"]
    kind = msg.get("type")
    try:
        op = await run_in_threadpool(_with_conn, ops_db.get_op, op_id)
    except ops_db.OpNotFound:
        op = None
    if op is None or op["document_id"] != document_id:
        await ws.send_json({"type": "op.error", "op_id": op_id, "code": "not_found"})
        return
    if kind == "op.applied":
        ids = msg.get("element_ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids)):
            await ws.send_json(
                {"type": "op.error", "op_id": op_id, "code": "bad_ack", "detail": "element_ids"}
            )
            return
        args = (op_id, "applied", list(dict.fromkeys(ids)), None)
    elif kind == "op.failed":
        args = (op_id, "failed", None, str(msg.get("error") or "unknown error")[:2000])
    else:
        await ws.send_json({"type": "error", "detail": f"unknown message type {kind!r}"})
        return
    try:
        op = await run_in_threadpool(_with_conn, ops_db.update_status, *args)
    except ops_db.OpNotFound:
        await ws.send_json({"type": "op.error", "op_id": op_id, "code": "not_found"})
        return
    except ops_db.ExistingElementIds as e:
        await ws.send_json(
            {"type": "op.error", "op_id": op_id, "code": "existing_element_id", "detail": e.ids}
        )
        return
    except ops_db.InvalidTransition as e:
        await ws.send_json(
            {"type": "op.error", "op_id": op_id, "code": "invalid_transition", "detail": e.current}
        )
        return
    await hub.send(document_id, updated_message(op))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, document: str = db.DEFAULT_DOCUMENT_ID) -> None:
    if not await run_in_threadpool(_with_conn, db.document_exists, document):
        await ws.close(code=4404, reason="unknown document")
        return
    await ws.accept()
    hub.join(document, ws)
    try:
        # Replay after joining, so an op created in between is pushed at least once (the browser
        # ignores a second copy of an op it already drew).
        for op in await run_in_threadpool(_with_conn, ops_db.list_ops, document, REPLAY_STATUSES):
            await ws.send_json(_pending_message(op))
            await run_in_threadpool(_with_conn, ops_db.mark_delivered, op["id"])
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except ValueError:
                await ws.send_json({"type": "error", "detail": "messages must be JSON"})
                continue
            await _handle(ws, document, msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(document, ws)
