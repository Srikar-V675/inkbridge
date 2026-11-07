"""MCP tools, one module per area. Importing this package registers every tool on ``app.mcp``."""

from inkbridge.mcp.tools import (
    canvas,
    memory,
    prompts,
    questions,
    regions,
    retrieve,
    sync,
    tasks,
    write,
)

__all__ = ["canvas", "memory", "prompts", "questions", "regions", "retrieve", "sync", "tasks", "write"]
