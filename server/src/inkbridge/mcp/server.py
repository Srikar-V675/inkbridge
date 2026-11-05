"""Inkbridge MCP server (stdio). Reads regions from the API; never touches the database.

stdout carries protocol frames only; all logging goes to stderr. The server object and client
live in ``app``; each tool area is a module in ``tools`` (imported here so the tools register).
"""

import logging
import sys

from inkbridge.mcp import app, tools  # noqa: F401  (tools registers on import)
from inkbridge.mcp.app import get_client, mcp, set_client

__all__ = ["get_client", "main", "mcp", "set_client"]


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        mcp.run("stdio")
    finally:  # release the HTTP connection pool when the client disconnects or we are stopped
        if app._client is not None:
            app._client.close()
        set_client(None)
