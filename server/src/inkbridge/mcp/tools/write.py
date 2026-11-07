"""Tools that add drafts to a canvas: write_text and draw_diagram."""

import time
from typing import Annotated, Literal
from urllib.parse import quote

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge import config
from inkbridge.mcp.app import _anchor_info, _dump, get_client, mcp
from inkbridge.mcp.client import ApiClient, ApiError, Conflict, NotFound


@mcp.tool()
def write_text(
    text: Annotated[str, Field(min_length=1, max_length=10_000, description="Plain text to add")],
    anchor: Annotated[
        str | None,
        Field(
            description="Chunk id from read_canvas; a replaced chunk is followed to its "
            "successor, a deleted one is refused. Ids change as the user writes, so re-read "
            "before anchoring. Omit for free space below the ink"
        ),
    ] = None,
    size: Annotated[
        Literal["small", "normal", "large"] | None,
        Field(description="Text size relative to the handwriting on the page; default matches it"),
    ] = None,
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
) -> str:
    """Add a text box to the canvas as a draft the user can accept or reject.

    The server picks the position: right of the anchor chunk (below it if that is taken), or
    below all existing ink, never overlapping it. Text is sized from the median handwriting stroke
    height of the anchor chunk (or the page) so it reads beside the ink. Never edits existing ink.
    The draft appears when the canvas is open in a browser (now, or the next time it is opened).
    Returns {op_id, status: "pending", placement, font_size, anchor_used, note}; anchor_used and
    note appear when an anchor was given (note when it was replaced by a successor). A deleted
    anchor is refused with `anchor_gone`.
    """
    client = get_client()
    payload = {
        "text": text,
        **({"anchor": anchor} if anchor else {}),
        **({"size": size} if size else {}),
    }
    try:
        op = client.create_op(document_id or client.default_document, "write_text", payload)
    except NotFound as e:
        raise ToolError(f"{e} Check document_id, or the anchor chunk id via read_canvas.") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(
        {
            "op_id": op["id"],
            "status": op["status"],
            "placement": op["payload"]["placement"],
            "font_size": op["payload"]["font_size"],
            **_anchor_info(op, anchor),
        }
    )


# How often draw_diagram checks whether the browser has drawn the op. Tests replace _sleep.
POLL_SECONDS = 0.25
_sleep = time.sleep
_clock = time.monotonic


def _canvas_url(document_id: str) -> str:
    return f"{config.public_url()}/?canvas={quote(document_id, safe='')}"


def _wait_for_browser(client: ApiClient, op: dict, wait_seconds: float) -> dict:
    """Poll the op until the browser measured or failed it, or the wait runs out."""
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
        Field(
            description="Chunk id from read_canvas; a replaced chunk is followed to its "
            "successor, a deleted one is refused. Ids change as the user writes, so re-read "
            "before anchoring. Omit for free space below"
        ),
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
    new, dashed draft elements. Returns {op_id, status: "placed", element_count, anchor_used, note}
    (the last two when an anchor was given; a replaced anchor is followed, a deleted one refused).
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
    if op["status"] == "placed":
        return _dump(
            {
                "op_id": op["id"],
                "status": "placed",
                "element_count": len(op.get("elements") or []),
                **_anchor_info(op, anchor),
            }
        )
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
