"""Tools that add drafts to a canvas: write_text and draw_diagram."""

import time
from typing import Annotated, Literal
from urllib.parse import quote

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge import config
from inkbridge.mcp.app import _anchor_info, _dump, get_client, mcp
from inkbridge.mcp.client import ApiClient, ApiError, Conflict, NotFound


def _question_link(question_id: str | None, relation: str | None) -> dict:
    return {
        **({"question_id": question_id} if question_id else {}),
        **({"relation": relation} if relation else {}),
    }


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
    question_id: Annotated[
        str | None,
        Field(
            description="Question this draft answers (from list_questions); links the draft to its "
            "thread"
        ),
    ] = None,
    relation: Annotated[
        Literal["answer", "diagram", "relates"] | None,
        Field(
            description="How the draft relates to the question; default answer when question_id is given"
        ),
    ] = None,
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    task_id: Annotated[
        str | None,
        Field(description="Task you claimed; the API enforces its mode and draft limit"),
    ] = None,
) -> str:
    """Add a text box to the canvas as a draft the user can accept or reject.

    The server picks the position: right of the anchor chunk (below it if that is taken), or
    below all existing ink, never overlapping it. Text is sized from the median handwriting stroke
    height of the anchor chunk (or the page) so it reads beside the ink. Never edits existing ink.
    The draft appears when the canvas is open in a browser (now, or the next time it is opened).
    Returns {op_id, status: "pending", document_id, placement, font_size, anchor_used, note}; anchor_used and
    note appear when an anchor was given (note when it was replaced by a successor). A deleted
    anchor is refused with `anchor_gone`.
    """
    client = get_client()
    doc = document_id or client.default_document
    payload = {
        "text": text,
        **({"anchor": anchor} if anchor else {}),
        **({"size": size} if size else {}),
        **({"task_id": task_id} if task_id else {}),
        **_question_link(question_id, relation),
    }
    try:
        op = client.create_op(doc, "write_text", payload)
    except NotFound as e:
        raise ToolError(f"{e} Check document_id, or the anchor chunk id via read_canvas.") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(
        {
            "op_id": op["id"],
            "status": op["status"],
            "document_id": doc,
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


def _draw(
    client: ApiClient, doc: str, payload: dict, anchor: str | None, wait_seconds: float, tool: str
) -> str:
    """Create a draw_diagram op, wait for the browser, map the outcome (shared by edit_diagram)."""
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
                "document_id": doc,
                "element_count": len(op.get("elements") or []),
                "diagram_id": op["diagram_id"],
                **({"revises": op["revises"]} if op.get("revises") else {}),
                **_anchor_info(op, anchor),
            }
        )
    if op["status"] == "failed":
        raise ToolError(
            f"{op['error'] or 'The browser could not draw the diagram.'} "
            f"Fix the source and call {tool} again."
        )
    if op["status"] == "expired":
        raise ToolError(
            f"No browser drew the diagram within {wait_seconds:g} s (op {op['id']} expired). "
            f"Open the canvas at {_canvas_url(doc)} and call {tool} again."
        )
    raise ToolError(f"The diagram op ended as {op['status']}.")


@mcp.tool()
def draw_diagram(
    source: Annotated[
        str,
        Field(
            min_length=1,
            max_length=20_000,
            description="Mermaid flowchart source (`flowchart TD` or `graph LR`), or with "
            "source_kind=graph a JSON string",
        ),
    ],
    source_kind: Annotated[
        Literal["mermaid", "graph"], Field(description="How to read source")
    ] = "mermaid",
    anchor: Annotated[
        str | None,
        Field(
            description="Chunk id from read_canvas; a replaced chunk is followed to its "
            "successor, a deleted one is refused. Ids change as the user writes, so re-read "
            "before anchoring. Omit for free space below"
        ),
    ] = None,
    from_chunks: Annotated[
        list[str] | None,
        Field(
            max_length=50,
            description="Chunk ids the diagram was made from; the user is offered a refresh when "
            "their readings change",
        ),
    ] = None,
    question_id: Annotated[
        str | None,
        Field(
            description="Question this draft answers (from list_questions); links the draft to its "
            "thread"
        ),
    ] = None,
    relation: Annotated[
        Literal["answer", "diagram", "relates"] | None,
        Field(
            description="How the draft relates to the question; default answer when question_id is given"
        ),
    ] = None,
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    wait_seconds: Annotated[
        float, Field(ge=1, le=60, description="How long to wait for the browser to draw it")
    ] = 20,
    task_id: Annotated[
        str | None,
        Field(description="Task you claimed; the API enforces its mode and draft limit"),
    ] = None,
) -> str:
    """Draw a diagram on the canvas as a draft the user can accept or reject.

    `source` is a Mermaid FLOWCHART (`flowchart` / `graph`; other diagram types are refused) or,
    with source_kind="graph", a JSON string {"nodes":[{"id","label","shape":"rect|ellipse|diamond"}],
    "edges":[{"from","to","label"?}]} laid out in the browser. `from_chunks` lists the chunk ids
    the diagram was made from, so it is flagged when their readings change. The canvas must be
    open in a browser: the source is converted there, and this call waits (default 20 s) for the
    browser to draw it. Never edits existing ink; it only adds new, dashed draft elements. Returns
    {op_id, status: "placed", document_id, element_count, diagram_id, anchor_used, note} (the last two when an
    anchor was given; a replaced anchor is followed, a deleted one refused). Revise an accepted
    diagram with edit_diagram.
    """
    client = get_client()
    doc = document_id or client.default_document
    payload = {
        "source": source,
        "source_kind": source_kind,
        **({"anchor": anchor} if anchor else {}),
        **({"from_chunks": from_chunks} if from_chunks else {}),
        **({"task_id": task_id} if task_id else {}),
        **_question_link(question_id, relation),
    }
    return _draw(client, doc, payload, anchor, wait_seconds, "draw_diagram")
