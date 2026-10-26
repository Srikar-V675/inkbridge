"""Inkbridge MCP server (stdio). Reads regions from the API; never touches the database.

stdout carries protocol frames only; all logging goes to stderr.
"""

import json
import logging
import sys
import time
from typing import Annotated
from urllib.parse import quote

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge import config
from inkbridge.mcp.client import ApiClient, ApiError, Conflict, NotFound
from inkbridge.sketch_prompts import sketch_prompt

mcp = MCPServer(
    "inkbridge",
    instructions=(
        "Inkbridge exposes saved regions of a handwritten canvas. Call list_regions first, "
        "then get_region for the image and transcription of one region."
    ),
)

_client: ApiClient | None = None


def set_client(client: ApiClient | None) -> None:
    global _client
    _client = client


def get_client() -> ApiClient:
    global _client
    if _client is None:
        _client = ApiClient()
    return _client


def _preview(text: str | None, n: int = 80) -> str | None:
    if not text:
        return None
    return text if len(text) <= n else text[: n - 1] + "…"


def _dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


@mcp.tool()
def list_regions(
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    kind: Annotated[str | None, Field(description="e.g. handwriting, equation, diagram")] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Max regions to return")] = 50,
) -> str:
    """List saved regions (most recently updated first) with bounds, stroke count and a text preview."""
    try:
        regions = get_client().list_regions(document_id, kind, limit)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(
        {
            "regions": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "bounds": r["bounds"],
                    "stroke_count": r["stroke_count"],
                    "preview": _preview(r["text"]),
                    "updated_at": r["updated_at"],
                }
                for r in regions
            ]
        }
    )


@mcp.tool()
def get_region(
    region_id: str,
    include_image: Annotated[bool, Field(description="Attach the cropped PNG")] = True,
    include_ink: Annotated[
        bool, Field(description="Include raw stroke points and pressures")
    ] = False,
    include_sketch: Annotated[
        bool,
        Field(
            description="For a hand-drawn diagram: add the server's guessed nodes and arrows "
            "and an image with numbered markers (two-pass sketch reading)"
        ),
    ] = False,
) -> list:
    """Get one region: transcription (text, latex), kind, bounds, optionally its PNG crop and ink."""
    client = get_client()
    try:
        r = client.get_region(region_id)
        meta = {
            k: r[k]
            for k in (
                "id",
                "kind",
                "text",
                "latex",
                "source",
                "bounds",
                "status",
                "png_stale",
                "updated_at",
            )
        }
        if include_ink:
            meta["ink"] = client.get_ink(region_id)
        if include_sketch:
            meta["sketch"] = client.get_sketch(region_id)
        content: list = [_dump(meta)]
    except ApiError as e:
        raise ToolError(str(e)) from e
    if include_image:
        try:
            content.append(Image(data=client.get_image(region_id), format="png"))
        except NotFound:
            # The transcription is still useful; do not fail the whole call over a missing crop.
            content.append("(image unavailable for this region; the crop file is missing)")
        except ApiError as e:
            # Any other failure is not a missing crop: keep the transcription, give the real cause.
            content.append(f"(image unavailable for this region: {e})")
    if include_sketch:
        try:
            content.append(Image(data=client.get_sketch_image(region_id), format="png"))
        except ApiError as e:
            content.append(f"(marker image unavailable: {e})")
    return content


@mcp.prompt()
def sketch_to_diagram(region_id: str, mode: str = "two_pass") -> str:
    """Turn a hand-drawn sketch region into a Mermaid flowchart drawn beside it as a draft.

    mode: two_pass (default; uses the server's node/arrow guess and a marker image) or one_shot.
    """
    return sketch_prompt(region_id, mode)


@mcp.tool()
def search(
    query: Annotated[str, Field(min_length=1, description="Words to find in transcriptions")],
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
) -> str:
    """Full-text search over region transcriptions (text and LaTeX). Matches are prefix-based."""
    try:
        hits = get_client().search(query, limit)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"results": hits})


# How often draw_diagram checks whether the browser has drawn the op. Tests replace _sleep.
POLL_SECONDS = 0.25
_sleep = time.sleep
_clock = time.monotonic


def _canvas_url(document_id: str) -> str:
    return f"{config.public_url()}/?canvas={quote(document_id, safe='')}"


def _wait_for_browser(client: ApiClient, op: dict, wait_seconds: float) -> dict:
    """Poll the op until the browser applied or failed it, or the wait runs out."""
    deadline = _clock() + wait_seconds
    while op["status"] in ("pending", "delivered") and _clock() < deadline:
        _sleep(POLL_SECONDS)
        op = client.get_op(op["id"])
    return op


@mcp.tool()
def draw_diagram(
    mermaid: Annotated[
        str,
        Field(
            min_length=1,
            max_length=20_000,
            description="Mermaid flowchart source, starting with `flowchart TD` or `graph LR`",
        ),
    ],
    anchor: Annotated[
        str | None,
        Field(description="Chunk id to place the diagram beside; omit for free space below"),
    ] = None,
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    wait_seconds: Annotated[
        float, Field(ge=1, le=60, description="How long to wait for the browser to draw it")
    ] = 20,
) -> str:
    """Draw a Mermaid FLOWCHART on the canvas as a draft the user can accept or reject.

    Only flowcharts (`flowchart` / `graph`) are supported; sequence, class and other diagram
    types are refused. The canvas must be open in a browser: Mermaid is converted there, and this
    call waits (default 20 s) for the browser to draw it. Never edits existing ink; it only adds
    new, dashed draft elements. Returns {op_id, status: "applied", element_count}.
    """
    client = get_client()
    doc = document_id or client.default_document
    payload = {"mermaid": mermaid, **({"anchor": anchor} if anchor else {})}
    try:
        op = client.create_op(doc, "draw_diagram", payload)
        op = _wait_for_browser(client, op, wait_seconds)
        if op["status"] in ("pending", "delivered"):
            # Give up for real: an expired op is never drawn later (a late browser sweeps it).
            try:
                op = client.set_op_status(op["id"], "expired")
            except Conflict:
                op = client.get_op(op["id"])  # the browser finished just now
    except NotFound as e:
        raise ToolError(f"{e} Check document_id, or the anchor chunk id via read_canvas.") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    if op["status"] == "applied":
        ids = (op.get("result") or {}).get("element_ids", [])
        return _dump({"op_id": op["id"], "status": "applied", "element_count": len(ids)})
    if op["status"] == "failed":
        raise ToolError(
            f"{op['error'] or 'The browser could not draw the diagram.'} "
            "Fix the Mermaid (flowchart syntax only) and call draw_diagram again."
        )
    if op["status"] == "expired":
        raise ToolError(
            f"No browser drew the diagram within {wait_seconds:g} s (op {op['id']} expired). "
            f"Open the canvas at {_canvas_url(doc)} and call draw_diagram again."
        )
    raise ToolError(f"The diagram op ended as {op['status']}.")


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        mcp.run("stdio")
    finally:  # release the HTTP connection pool when the client disconnects or we are stopped
        if _client is not None:
            _client.close()
        set_client(None)
