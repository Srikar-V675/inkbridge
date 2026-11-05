"""Tools that read single regions and chunks."""

from typing import Annotated

from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge import imaging
from inkbridge.mcp.app import _dump, _preview, get_client, mcp
from inkbridge.mcp.client import ApiError, NotFound


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
