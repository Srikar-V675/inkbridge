"""WebSocket push channel (INK-042, tech ref 7.3): `WS /ws?document={id}`.

server -> browser: `op.pending {op_id, type, payload}`, `op.updated {op_id, status, error}`,
`op.error {op_id, code, detail}` (a refused ack), `chunks.updated {version, stale_crops}`,
`op.placed {op_id, elements, placement, anchor}` (INK-114: the server placed the measured drafts),
`question.update {question}` (INK-047), `question.delta {id, seq, text}` (INK-176),
`scene.delta {seq, origin, elements}` (INK-112; not sent to the socket whose `device` is `origin`),
`offer.created {offer}` and `offer.updated {offer}` (INK-130; only while the attention gate is open).
browser -> server: `attention {pen, view}` (INK-130; any frame, pen down or up, counts as a stroke
moment), `op.measured {op_id, elements, width, height}` (the drafts as drawn, to be
placed), `op.failed {op_id, error}`.

On every connect the server replays all pending and delivered ops for the document; an op is
marked delivered once one browser got it, and every placed op follows as `op.placed`. Ops are idempotent by op_id: the browser checks for
elements it already drew for that op before drawing again.

HTTP routes run in the threadpool, so they publish through `hub.publish`, which hands the send
to the event loop that owns the sockets.
"""

import asyncio
import concurrent.futures
import json
import logging
import math
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from inkbridge import db
from inkbridge.agent.attention import attention
from inkbridge.db import drafts
from inkbridge.db import ops as ops_db
from inkbridge.db.common import _now

router = APIRouter()
log = logging.getLogger(__name__)

REPLAY_STATUSES = ["pending", "delivered"]


def _same_origin(ws: WebSocket) -> bool:
    """Browsers do not apply CORS to WebSockets, so any page the user opens could connect and read
    or ack ops. Only a page served from this host (directly or through the Vite proxy, which keeps
    the Host header) may connect; clients without an Origin (scripts, tests) are not browsers."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == ws.headers.get("host", "").lower()


def _pending_message(op: dict) -> dict:
    return {
        "type": "op.pending",
        "op_id": op["id"],
        "op_type": op["type"],
        "payload": op["payload"],
    }


def updated_message(op: dict) -> dict:
    return {"type": "op.updated", "op_id": op["id"], "status": op["status"], "error": op["error"]}


def _placed_message(op: dict) -> dict:
    return {
        "type": "op.placed",
        "op_id": op["id"],
        "elements": op["elements"],
        "placement": {"x": op["box"]["x"], "y": op["box"]["y"]},
        "anchor": op["payload"].get("anchor_resolved"),
    }


def _with_conn(fn, *args):
    conn = db.connect()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}
        self._device: dict[WebSocket, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: dict[str, str] = {}  # document -> when its first socket joined

    def session_start(self, document_id: str) -> str:
        """'' until a browser has joined, so all history counts toward the mute (INK-130)."""
        return self._session.get(document_id, "")

    def join(self, document_id: str, ws: WebSocket, device: str = "") -> None:
        self._device[ws] = device
        self._loop = asyncio.get_running_loop()
        if not self._sockets.get(document_id):
            self._session[document_id] = _now()
        self._sockets.setdefault(document_id, set()).add(ws)

    def leave(self, document_id: str, ws: WebSocket) -> None:
        self._sockets.get(document_id, set()).discard(ws)
        self._device.pop(ws, None)
        if not self._sockets.get(document_id):
            attention.forget(document_id)  # no browser, no attention

    def connected(self, document_id: str) -> int:
        return len(self._sockets.get(document_id, ()))

    async def send(self, document_id: str, message: dict) -> int:
        """Send to every socket of the document; return how many got it."""
        sent = 0
        origin = message.get("origin")
        for ws in list(self._sockets.get(document_id, ())):
            if origin and self._device.get(ws) == origin:
                continue  # the writer already has this change
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

    def publish(
        self, document_id: str, message: dict | None = None, op: dict | None = None
    ) -> concurrent.futures.Future | None:
        """Thread-safe, fire and forget. With `op`, push it as op.pending (and mark delivered).

        Returns the scheduled send (None if no browser is connected); callers need not wait.
        """
        loop = self._loop
        if loop is None or loop.is_closed() or not self.connected(document_id):
            return None
        coro = self.push_op(document_id, op["id"]) if op else self.send(document_id, message or {})
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.add_done_callback(_log_failure)
        return future


def _log_failure(future) -> None:
    if not future.cancelled() and future.exception() is not None:
        log.error("websocket publish failed", exc_info=future.exception())


hub = Hub()


_VIEW_KEYS = ("x", "y", "width", "height", "zoom")


def _good_attention(msg: dict) -> bool:
    view = msg.get("view")
    if not isinstance(msg.get("pen"), bool):
        return False
    return view is None or (
        isinstance(view, dict)
        and all(
            isinstance(view.get(k), int | float)
            and not isinstance(view.get(k), bool)
            and math.isfinite(view[k])
            for k in _VIEW_KEYS
        )
    )


async def _handle(ws: WebSocket, document_id: str, msg: Any) -> None:
    if isinstance(msg, dict) and msg.get("type") == "attention":
        if not _good_attention(msg):
            await ws.send_json({"type": "error", "detail": "bad attention"})
            return
        from inkbridge.api import offers  # lazy: offers imports the hub from this module

        attention.update(document_id, msg["pen"], msg.get("view"))
        await run_in_threadpool(offers.flush, document_id)
        return
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
    if kind == "op.measured":
        try:
            op = await run_in_threadpool(
                _with_conn,
                drafts.measure_op,
                op_id,
                msg.get("elements"),
                msg.get("width"),
                msg.get("height"),
            )
        except ValueError:
            await ws.send_json({"type": "op.error", "op_id": op_id, "code": "bad_measure"})
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
        await hub.send(document_id, _placed_message(op))
        return
    elif kind == "op.failed":
        args = (op_id, "failed", str(msg.get("error") or "unknown error")[:2000])
    else:
        await ws.send_json({"type": "error", "detail": f"unknown message type {kind!r}"})
        return
    try:
        op = await run_in_threadpool(_with_conn, ops_db.update_status, *args)
    except ops_db.OpNotFound:
        await ws.send_json({"type": "op.error", "op_id": op_id, "code": "not_found"})
        return
    except ops_db.InvalidTransition as e:
        await ws.send_json(
            {"type": "op.error", "op_id": op_id, "code": "invalid_transition", "detail": e.current}
        )
        return
    await hub.send(document_id, updated_message(op))


@router.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket, document: str = db.DEFAULT_DOCUMENT_ID, device: str = ""
) -> None:
    if not _same_origin(ws):
        await ws.close(code=4403, reason="cross-origin")
        return
    if not await run_in_threadpool(_with_conn, db.document_exists, document):
        await ws.close(code=4404, reason="unknown document")
        return
    await ws.accept()
    device = device if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device) else ""
    hub.join(document, ws, device)
    try:
        # Replay after joining, so an op created in between is pushed at least once (the browser
        # ignores a second copy of an op it already drew).
        swept: list[dict] = []
        replay = await run_in_threadpool(
            _with_conn, ops_db.list_ops, document, REPLAY_STATUSES, swept
        )
        for op in swept:  # this sweep expired them; sockets that already drew them must drop them
            await hub.send(document, updated_message(op))
        for op in replay:
            await ws.send_json(_pending_message(op))
            await run_in_threadpool(_with_conn, ops_db.mark_delivered, op["id"])
        for op in await run_in_threadpool(_with_conn, drafts.list_drafts, document):
            await ws.send_json(_placed_message(op))  # a late tab gets the drafts without a GET
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(frame.get("code", 1000))
            try:
                msg = json.loads(frame["text"])  # a binary frame has no "text" (or None)
            except (KeyError, TypeError, ValueError):
                await ws.send_json({"type": "error", "detail": "messages must be JSON"})
                continue
            await _handle(ws, document, msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(document, ws)
