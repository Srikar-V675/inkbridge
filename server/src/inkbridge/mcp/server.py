"""Inkbridge MCP server (stdio). Reads regions from the API; never touches the database.

stdout carries protocol frames only; all logging goes to stderr.
"""

import json
import logging
import sys
import time
from typing import Annotated, Literal
from urllib.parse import quote

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from inkbridge import config, imaging
from inkbridge.mcp.client import ApiClient, ApiError, Conflict, NotFound
from inkbridge.sketch_prompts import sketch_prompt

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


def _anchor_info(op: dict, anchor: str | None) -> dict:
    """Which chunk the server actually placed beside (INK-084); a note when it differs."""
    used = (op.get("payload") or {}).get("anchor_resolved")
    if not used:
        return {}
    info = {"anchor_used": used}
    if used != anchor:
        info["note"] = f"anchor {anchor} was replaced by {used}; use {used} from now on"
    return info


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
    """Get one region: transcription (text, latex), kind, bounds, optionally its PNG crop and ink.

    An orphaned (replaced or deleted) chunk returns only {id, status, live_successor, note}: its
    old ink is not served; read the live successor, or call read_canvas.
    read_status `too_large` means the chunk is not readable at a useful scale: no image is sent;
    ask the user to split it, do not guess its content.
    """
    client = get_client()
    try:
        r = client.get_region(region_id)
        if r["status"] != "active":
            # Stale ink must not be read as current (INK-084): point at the live chunk instead.
            live = r.get("live_successor")
            return [
                _dump(
                    {
                        "id": r["id"],
                        "status": r["status"],
                        "live_successor": live,
                        "note": f"this chunk was replaced; read {live} instead"
                        if live
                        else "this chunk no longer exists; call read_canvas for current chunks",
                    }
                )
            ]
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
        why = imaging.unreadable_reason(r["bounds"], r["stroke_count"])
        meta["read_status"] = "too_large" if why else "ok"
        meta["read_note"] = why
        content: list = [_dump(meta)]
    except ApiError as e:
        raise ToolError(str(e)) from e
    if why:
        # A crop of this chunk would be downscaled past reading (INK-096): say so, send no image.
        content.append(f"(no image: {why})")
    elif include_image:
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


class Source(BaseModel):
    """A local copy of the API's shape; the API stays the one place that enforces it."""

    type: Literal["chunk", "note"]
    id: str | None = Field(default=None, description="Chunk id (type chunk)")
    path: str | None = Field(default=None, description="Vault note path (type note)")


_NEXT_STEP = "Call list_questions to see the pending question ids."


@mcp.tool()
def list_questions(
    status: Annotated[
        Literal["pending", "answered", "cancelled"],
        Field(description="Which questions to list"),
    ] = "pending",
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> str:
    """Questions the user asked on the canvas, oldest first (default: the pending ones).

    Each has focus_chunk_ids (read them with get_region or read_canvas), parent_id and history
    (earlier question/answer pairs of the thread, oldest first). Reply with answer_question.
    """
    client = get_client()
    try:
        questions = client.list_questions(document_id, status, limit)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"questions": questions})


@mcp.tool()
def answer_question(
    question_id: str,
    answer_md: Annotated[str, Field(min_length=1, max_length=20_000, description="Markdown")],
    sources: Annotated[
        list[Source],
        Field(description="What the answer rests on: {type:'chunk', id} or {type:'note', path}"),
    ] = [],  # noqa: B006 - never mutated
) -> str:
    """Answer a pending question. Stores the text only; it changes no ink and writes no note.

    Fails if the question is already answered or cancelled.
    """
    try:
        q = get_client().answer_question(
            question_id, answer_md, [s.model_dump(exclude_none=True) for s in sources]
        )
    except (NotFound, Conflict) as e:
        raise ToolError(f"{e} {_NEXT_STEP}") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"id": q["id"], "status": q["status"]})


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
    "read_status",
    "read_note",
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
    arrow links to other chunks (at most 20 each, the rest counted in links_omitted) and a deep_link that opens it in the web app. text is null when the
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
    head = {k: data[k] for k in ("document", "version", "chunk_count")}
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

    Read-only; only long arrows between chunks count as links (short ones merge chunks). Each
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
    new, dashed draft elements. Returns {op_id, status: "applied", element_count, anchor_used, note}
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
    if op["status"] == "applied":
        ids = (op.get("result") or {}).get("element_ids", [])
        return _dump(
            {
                "op_id": op["id"],
                "status": "applied",
                "element_count": len(ids),
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


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        mcp.run("stdio")
    finally:  # release the HTTP connection pool when the client disconnects or we are stopped
        if _client is not None:
            _client.close()
        set_client(None)
