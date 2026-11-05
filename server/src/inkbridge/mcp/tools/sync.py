"""check_sync: which note sections are stale."""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError, NotFound


class NoteChunk(BaseModel):
    id: Annotated[str, Field(min_length=1, description="Chunk id from the note's frontmatter")]
    hash: Annotated[str, Field(min_length=1, description="The chunk's content hash in the note")]
    reading: Annotated[
        str | None, Field(description="The reading hash (text_hash) in the note, or null")
    ] = None


@mcp.tool()
def check_sync(
    chunks: Annotated[
        list[NoteChunk], Field(max_length=2000, description="The note's chunks: id, hash, reading")
    ],
    document_id: Annotated[
        str | None, Field(description="Canvas id; defaults to the configured document")
    ] = None,
    wait_s: Annotated[
        float, Field(ge=0, le=30, description="Max seconds to wait for new readings")
    ] = 15,
) -> str:
    """Check which sections of a note are out of date with the canvas (early cutoff).

    Returns ids under `fresh` (unchanged or moved), objects under `fresh_after_reread` (ink
    changed but reads the same: only update the stored hash), `changed` (rewrite that block;
    `reading` null means no reading was available in time, so look at the chunk with
    get_region), `replaced` (split or merged: rewrite from `successor`), `removed` (gone), and
    `new` (chunks not in the note, in reading order, with a preview). Never changes the canvas.
    """
    try:
        result = get_client().check_sync(document_id, [c.model_dump() for c in chunks], wait_s)
    except NotFound as e:
        raise ToolError(
            f"Unknown canvas {document_id or get_client().default_document!r}: {e}"
        ) from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(result)
