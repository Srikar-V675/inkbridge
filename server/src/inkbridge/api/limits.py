"""Request body caps, enforced before any route parses the body (decision 0010).

FastAPI reads a JSON body whole and Starlette spools a multipart upload to disk before a route
runs, so a route-level check comes too late. This middleware answers 413 when the declared
Content-Length is over the cap, and otherwise reads the body up to the cap (which also covers
chunked uploads that declare no length) before replaying it to the app.
"""

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from inkbridge.api.regions import MAX_UPLOAD_BYTES

# Scenes: the whole canvas is one PUT, and a long freedraw stroke with pressures is ~35 KB, so
# 128 MiB is room for a few thousand dense strokes. It bounds memory, it is not a content limit.
MAX_BODY_BYTES = 128 * 1024 * 1024
# Crop uploads: the 10 MB PNG cap plus room for multipart framing and form fields.
MAX_IMAGE_BODY_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024

_IMAGE_ROUTES = (
    ("POST", re.compile(r"^/documents/.+/regions$")),
    ("PUT", re.compile(r"^/regions/.+/image$")),
)


def cap_for(method: str, path: str) -> int:
    if any(method == m and p.match(path) for m, p in _IMAGE_ROUTES):
        return MAX_IMAGE_BODY_BYTES
    return MAX_BODY_BYTES


class BodySizeLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cap = cap_for(scope["method"], scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = not 0 <= int(declared) <= cap
            except ValueError:
                too_big = False  # the server rejects a malformed length before we get here
            if too_big:
                # Not draining the body: uvicorn closes the connection after the response.
                await _reject(send, cap)
                return

        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break  # client disconnected; let the app see it
            size += len(message.get("body", b""))
            if size > cap:
                await _reject(send, cap)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


async def _reject(send: Send, cap: int) -> None:
    body = json.dumps({"detail": f"request body too large ({cap} bytes max)"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
