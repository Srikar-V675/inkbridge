"""MCP prompts."""

from inkbridge.canvas.sketch_prompts import sketch_prompt
from inkbridge.mcp.app import mcp


@mcp.prompt()
def sketch_to_diagram(region_id: str, mode: str = "two_pass") -> str:
    """Turn a hand-drawn sketch region into a Mermaid flowchart drawn beside it as a draft.

    mode: two_pass (default; uses the server's node/arrow guess and a marker image) or one_shot.
    """
    return sketch_prompt(region_id, mode)
