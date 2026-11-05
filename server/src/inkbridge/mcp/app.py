"""The MCP server object and its API client, shared by every tool module."""

import json

from mcp.server.mcpserver import MCPServer

from inkbridge.mcp.client import ApiClient

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


def _anchor_info(op: dict, anchor: str | None) -> dict:
    """Which chunk the server actually placed beside (INK-084); a note when it differs."""
    used = (op.get("payload") or {}).get("anchor_resolved")
    if not used:
        return {}
    info = {"anchor_used": used}
    if used != anchor:
        info["note"] = f"anchor {anchor} was replaced by {used}; use {used} from now on"
    return info
