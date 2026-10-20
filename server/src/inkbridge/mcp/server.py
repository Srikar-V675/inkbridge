"""Inkbridge MCP server (stdio). Reads regions from the API; never touches the database.

stdout carries protocol frames only; all logging goes to stderr.
"""

import json
import logging
import sys
from typing import Annotated

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge.mcp.client import ApiClient, ApiError

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
            for k in ("id", "kind", "text", "latex", "source", "bounds", "status", "updated_at")
        }
        if include_ink:
            meta["ink"] = client.get_ink(region_id)
        content: list = [_dump(meta)]
        if include_image:
            content.append(Image(data=client.get_image(region_id), format="png"))
    except ApiError as e:
        raise ToolError(str(e)) from e
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


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run("stdio")
