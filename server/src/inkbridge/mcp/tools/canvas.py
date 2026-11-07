"""Tools that read or create whole canvases: read_canvas, search, graph views."""

from typing import Annotated, Literal

from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge import imaging
from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError


@mcp.tool()
def create_canvas(
    title: Annotated[str, Field(min_length=1, max_length=200, description="Canvas title")],
) -> str:
    """Create a new, empty canvas. Returns {document_id, url}; open the url to see it.

    Only ever adds a canvas; it cannot change an existing one. Write into it with write_text and
    draw_diagram (pass document_id); their content arrives as drafts.
    """
    try:
        doc = get_client().create_document(title)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"document_id": doc["id"], "url": doc["url"]})


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
MAX_GROUPS = 20  # top-level groups shown; the rest are counted in groups_omitted
MAX_GROUP_IDS = 20  # chunk ids per group; the rest are counted in omitted_ids
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
    "group_id",
    "deep_link",
    "read_status",
    "read_note",
)


def _groups(data: dict) -> dict:
    gs = data.get("groups") or []
    shown = []
    for g in gs[:MAX_GROUPS]:
        ids = g["chunk_ids"]
        item = {"id": g["id"], "chunk_ids": ids[:MAX_GROUP_IDS]}
        if len(ids) > MAX_GROUP_IDS:
            item["omitted_ids"] = len(ids) - MAX_GROUP_IDS
        shown.append(item)
    out = {"groups": shown}
    if len(gs) > MAX_GROUPS:
        out["groups_omitted"] = len(gs) - MAX_GROUPS
    return out


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
        bool, Field(description="Attach PNGs of the canvas with chunk ids (a spread one in bands)")
    ] = True,
    offset: Annotated[
        int, Field(ge=0, description="Skip this many chunks (to continue a cut outline)")
    ] = 0,
    max_width: Annotated[
        int, Field(ge=256, le=1568, description="Width of each overview image in px")
    ] = 1568,
) -> list:
    """Read the whole canvas: its chunks in reading order, then overview images.

    Each chunk has order, kind, bounds, its reading (text, latex), status, png_stale, content_hash,
    text_hash (the reading's hash, what a vault note stores as `reading`),
    arrow links to other chunks as {to, kind, label, confidence} (at most 20 each, the rest counted
    in links_omitted), group_id, and a deep_link that opens it in the web app.
    groups lists the connected components of 2 or more chunks joined by arrows (largest first,
    at most 20 groups of 20 chunk ids; groups_omitted and omitted_ids count the rest). A chunk
    with group_id null stands on its own. groups repeats on every page, so a continued read keeps it. text is null when the
    chunk has not been read yet: call get_region with its id to look at its image instead. A very
    large canvas is cut at a size cap; the reply then says how many chunks were omitted and which
    offset continues it.
    read_status `too_large` (with read_note) means the chunk is not readable at a useful scale:
    ask the user to split it, do not guess.
    The overview images are for orientation only: a spread-out canvas is drawn in several images
    (at most three per call, in reading order), and the reply names the offset that continues
    them. Read a chunk's ink and reading with get_region.
    """
    client = get_client()
    try:
        data = client.get_chunks(document_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    head = {**{k: data[k] for k in ("document", "version", "chunk_count")}, **_groups(data)}
    chunks = [_outline_chunk(c) for c in data["chunks"][offset:]]
    content: list = [_fit(head, chunks, offset)]
    if include_overview:
        pos, nxt = offset, None
        try:
            for _ in range(imaging.MAX_OVERVIEW_IMAGES):
                png, nxt = client.get_overview(document_id, max_width, pos)
                content.append(Image(data=png, format="png"))
                if nxt is None:
                    break
                pos = nxt
        except ApiError as e:
            content.append(f"(overview unavailable: {e})")
            nxt = None
        if nxt is not None:
            content.append(
                f"Overview shows chunks {offset + 1}..{nxt} of {data['chunk_count']}; "
                f"call read_canvas with offset={nxt} for the rest."
            )
    return content


@mcp.tool()
def get_subgraph(
    chunk_id: Annotated[str, Field(description="Chunk id from read_canvas to start from")],
    depth: Annotated[int, Field(ge=1, le=5, description="Arrow hops to follow")] = 1,
    direction: Annotated[
        Literal["both", "out", "in"],
        Field(description="out follows arrows, in goes against them, both ignores direction"),
    ] = "both",
    to_chunk_id: Annotated[
        str | None,
        Field(description="Set to get the shortest arrow path chunk_id -> to_chunk_id instead"),
    ] = None,
    max_nodes: Annotated[int, Field(ge=1, le=100, description="Max chunks returned")] = 40,
    mermaid: Annotated[bool, Field(description="Also return flowchart text of the result")] = False,
    document_id: Annotated[
        str | None, Field(description="Canvas to read; defaults to the configured document")
    ] = None,
) -> str:
    """Chunks connected to one chunk by arrows, or the shortest arrow path between two chunks.

    Read-only; only long arrows between chunks count as links (short ones merge chunks; with
    the v2 chunker pen and native connectors are links at any length above a tick). Each
    node has id, order, kind, a text preview, distance and a deep_link. An orphaned (replaced)
    chunk id is followed to its live successor: see anchor_used and note. A deleted chunk is
    refused; call read_canvas. omitted_nodes / omitted_edges say what the caps cut. mermaid
    returns `flowchart TD` text only; nothing is drawn on the canvas.
    """
    client = get_client()
    try:
        if to_chunk_id is not None:
            data = client.get_graph_path(document_id, chunk_id, to_chunk_id, direction, mermaid)
        else:
            data = client.get_subgraph(
                document_id, chunk_id, depth, direction, max_nodes, None, mermaid
            )
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(data, True)


@mcp.tool()
def canvas_components(
    document_id: Annotated[
        str | None, Field(description="Canvas to read; defaults to the configured document")
    ] = None,
) -> str:
    """Groups of chunks joined by arrows, largest first, and how many chunks stand alone.

    Read-only. At most 30 groups with at most 20 chunk ids each; omitted_components and
    omitted_ids count the rest. Only active chunks are listed.
    """
    try:
        data = get_client().get_components(document_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(data, True)
