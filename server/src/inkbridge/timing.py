"""Timing logs for the API process. Counts and milliseconds only: never scene content, keys or
readings (INK-067). Imports nothing from inkbridge.db, so the MCP boundary test is unaffected."""

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SLOW_S = 1.0
SCOPE_KEY = "inkbridge.timing"
req_log = logging.getLogger("inkbridge.request")
log = logging.getLogger("inkbridge.timing")


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def mark_recv(scope: Scope, start: float, end: float) -> None:
    """BodySizeLimit calls this once the whole body is in (INK-102)."""
    scope[SCOPE_KEY] = {"recv": _ms(end - start), "_end": end}


def request_parts(scope: Scope, now: float) -> dict[str, float]:
    """recv and queue in ms; {} when the middleware did not run. `now` is the first line of the handler."""
    m = scope.get(SCOPE_KEY)
    if m is None:
        return {}
    return {"recv": m["recv"], "queue": _ms(now - m["_end"])}


@contextmanager
def timed(name: str, **counts: int) -> Iterator[None]:
    for k, v in counts.items():
        if type(v) is not int:
            raise TypeError(f"timing count {k!r} must be an int")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        extra = "".join(f" {k}={v}" for k, v in counts.items())
        log.log(
            logging.WARNING if elapsed > SLOW_S else logging.INFO,
            "%s%s ms=%.0f",
            name,
            extra,
            elapsed * 1000,
        )


class RequestTiming:
    """Pure ASGI (not BaseHTTPMiddleware: it would buffer and slow streaming/WebSocket)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500

        async def wrapped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, wrapped)
        finally:
            elapsed = time.perf_counter() - start
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"  # template, never a raw id or query
            req_log.log(
                logging.WARNING if elapsed > SLOW_S else logging.INFO,
                "%s %s status=%d ms=%.0f",
                scope["method"],
                path,
                status,
                elapsed * 1000,
            )


def configure_logging() -> None:
    """uvicorn only configures its own loggers, so inkbridge.* INFO lines are dropped by default."""
    top = logging.getLogger("inkbridge")
    if not top.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
        top.addHandler(h)
    top.setLevel(logging.INFO)
