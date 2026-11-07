"""MCP tools, one module per area. Importing this package registers every tool on ``app.mcp``."""

from inkbridge.mcp.tools import canvas, prompts, questions, regions, retrieve, sync, write

__all__ = ["canvas", "prompts", "questions", "regions", "retrieve", "sync", "write"]
