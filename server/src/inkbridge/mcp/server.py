"""Inkbridge MCP server (stdio). Reads regions from the API; never touches the database.

stdout carries protocol frames only; all logging goes to stderr.
"""

import json
import logging
import sys
from typing import Annotated

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from inkbridge.mcp.client import ApiClient, ApiError, NotFound

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
    return content


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


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        mcp.run("stdio")
    finally:  # release the HTTP connection pool when the client disconnects or we are stopped
        if _client is not None:
            _client.close()
        set_client(None)
