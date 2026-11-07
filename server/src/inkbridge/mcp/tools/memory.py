"""Canvas brief and what_changed (INK-135, decision 0093)."""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError

_DOC = Field(description="Canvas to use; defaults to the configured document")


@mcp.tool()
def what_changed(
    document_id: Annotated[str | None, _DOC] = None,
    since: Annotated[
        int | None, Field(ge=0, description="Seq to compare with; default is the saved cursor")
    ] = None,
    mark_seen: Annotated[bool, Field(description="Move the saved cursor to the head")] = False,
) -> str:
    """Chunks whose ink changed since seq `since` (default: this canvas's saved last_seen_seq).

    `change` is `changed` (new or edited: read it with get_region) or `removed`. Readings that
    arrive later are not changes. Call with mark_seen=true after you have acted on the result so
    the next call starts there; `seq` in the reply is the head to remember. Read-only for the canvas.
    """
    try:
        data = get_client().get_changes(document_id, since, mark_seen)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(data, True)


@mcp.tool()
def set_canvas_brief(
    brief: Annotated[str, Field(max_length=4000, description="1 to 10 lines")],
    document_id: Annotated[str | None, _DOC] = None,
) -> str:
    """Store 1 to 10 lines saying what this canvas is about, who it is for and what is in progress.

    Replaces the previous brief. Kept in Inkbridge's database, never written to the vault; the
    user's ink is not touched. read_canvas returns it first.
    """
    try:
        data = get_client().set_brief(document_id, brief)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(data, True)
