"""The retrieve tool: related ink and past answers across canvases (INK-136, decision 0079)."""

from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError


@mcp.tool()
def retrieve(
    query: Annotated[
        str, Field(min_length=1, description="Words to find in readings and past answers")
    ],
    scope: Annotated[
        Literal["canvas", "all"], Field(description="canvas = one canvas, all = every canvas")
    ] = "canvas",
    k: Annotated[int, Field(ge=1, le=50)] = 8,
    document_id: Annotated[
        str | None,
        Field(description="Canvas for scope=canvas; defaults to the configured document"),
    ] = None,
) -> str:
    """Find related ink and past answers, on this canvas or across canvases (read-only).

    A prefix keyword match over chunk readings and answered questions, never vault notes: search
    the vault with your own tool and merge by relevance yourself. Results are ranked best first,
    each with kind ("chunk" or "answer"), id, chunk_id, canvas, canvas_title, snippet, deep_link
    and source. Open a chunk with get_region (it takes the chunk id) or give the user the
    deep_link. It creates no links between canvases.
    """
    try:
        body = get_client().retrieve(query, scope, k, document_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(body)
