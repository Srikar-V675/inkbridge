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
        "Inkbridge exposes a handwritten canvas split into chunks (one idea each). Call "
        "read_canvas first for the whole canvas in reading order, then get_region for the image "
        "and transcription of one chunk or saved region."
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


def _dump(obj: dict, compact: bool = False) -> str:
    if compact:  # read by a model: indentation only costs tokens
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
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
    document_id: Annotated[
        str | None, Field(description="Canvas to search; defaults to the configured document")
    ] = None,
) -> str:
    """Full-text search over region transcriptions (text and LaTeX). Matches are prefix-based."""
    try:
        hits = get_client().search(query, limit, document_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"results": hits})


# The outline JSON text never exceeds this (about 15k tokens), whatever the canvas holds.
READ_CANVAS_MAX_CHARS = 60_000
MAX_READING_CHARS = 4_000  # per chunk; a longer reading is cut and flagged
MAX_LINKS = 20  # per chunk; the rest are counted in links_omitted
_OUTLINE_FIELDS = (
    "id",
    "order",
    "kind",
    "bounds",
    "text",
    "latex",
    "status",
    "png_stale",
    "content_hash",
    "text_hash",
    "links",
    "deep_link",
)


def _outline_chunk(c: dict) -> dict:
    out = {k: c.get(k) for k in _OUTLINE_FIELDS}
    for field in ("text", "latex"):
        value = out[field]
        if value and len(value) > MAX_READING_CHARS:
            out[field] = value[: MAX_READING_CHARS - 1] + "…"
            out[f"{field}_truncated"] = True
    links = out["links"] or []
    if len(links) > MAX_LINKS:
        out["links"] = links[:MAX_LINKS]
        out["links_omitted"] = len(links) - MAX_LINKS
    return out


def _note(omitted: int, next_offset: int) -> str:
    return (
        f"{omitted} more chunks omitted (size cap). Call read_canvas with "
        f"offset={next_offset} and include_overview=false for the rest."
    )


def _fit(head: dict, chunks: list[dict], offset: int) -> str:
    """The outline as compact JSON, as many chunks as fit under READ_CANVAS_MAX_CHARS.

    Chunks are bounded (readings and links are capped), so at least one always fits and a
    continuation offset always moves forward.
    """
    # Room for the head and the longest possible note.
    biggest = len(chunks) + offset
    size = len(
        _dump({**head, "chunks": [], "omitted": biggest, "note": _note(biggest, biggest)}, True)
    )
    shown: list[dict] = []
    for c in chunks:
        extra = len(_dump(c, True)) + 1
        if size + extra > READ_CANVAS_MAX_CHARS:
            break
        shown.append(c)
        size += extra
    body = {**head, "chunks": shown}
    omitted = len(chunks) - len(shown)
    if omitted:
        body["omitted"] = omitted
        body["note"] = _note(omitted, offset + len(shown))
    return _dump(body, True)


@mcp.tool()
def read_canvas(
    document_id: Annotated[
        str | None, Field(description="Canvas to read; defaults to the configured document")
    ] = None,
    include_overview: Annotated[
        bool, Field(description="Attach one PNG of the whole canvas with chunk ids")
    ] = True,
    offset: Annotated[
        int, Field(ge=0, description="Skip this many chunks (to continue a cut outline)")
    ] = 0,
) -> list:
    """Read the whole canvas: its chunks in reading order, then an overview image.

    Each chunk has order, kind, bounds, its reading (text, latex), status, png_stale, content_hash,
    text_hash (the reading's hash, what a vault note stores as `reading`),
    arrow links to other chunks (at most 20 each, the rest counted in links_omitted) and a deep_link that opens it in the web app. text is null when the
    chunk has not been read yet: call get_region with its id to look at its image instead. A very
    large canvas is cut at a size cap; the reply then says how many chunks were omitted and which
    offset continues it.
    """
    client = get_client()
    try:
        data = client.get_chunks(document_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    head = {k: data[k] for k in ("document", "version", "chunk_count")}
    chunks = [_outline_chunk(c) for c in data["chunks"][offset:]]
    content: list = [_fit(head, chunks, offset)]
    if include_overview:
        try:
            content.append(Image(data=client.get_overview(document_id), format="png"))
        except ApiError as e:
            content.append(f"(overview unavailable: {e})")
    return content


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
