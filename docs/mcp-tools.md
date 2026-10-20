# MCP tools

Server: `inkbridge-mcp` (stdio). A thin HTTP client of the API; it never imports `inkbridge.db`
(enforced by `server/tests/test_mcp_boundary.py`). stdout carries protocol frames only; logs go to stderr.
Built on the MCP Python SDK 2.x (`MCPServer`, formerly `FastMCP`).

Env: `INKBRIDGE_API_URL` (default `http://127.0.0.1:8000`), `INKBRIDGE_DOCUMENT` (default `default`).

## Client config

Claude Code:

```bash
claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "inkbridge": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/inkbridge/server", "inkbridge-mcp"],
      "env": { "INKBRIDGE_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

Never run a script from inside `server/src/inkbridge/mcp/` (the directory name shadows the SDK); use the entry point or `python -m inkbridge.mcp`.

## Tools

| Tool | Input | Returns | Mutates |
|---|---|---|---|
| `list_regions` | `document_id?`, `kind?`, `limit=50` | JSON `{regions: [{id, kind, bounds, stroke_count, preview, updated_at}]}` | No |
| `get_region` | `region_id`, `include_image=true`, `include_ink=false` | JSON text `{id, kind, text, latex, source, bounds, status, updated_at, ink?}` plus the region PNG as image content | No |

Errors are returned as tool errors with a next step (for example, "call list_regions to see valid region ids").

## Limits

- Images are downscaled to at most 1024 px wide (API default; the stored crop is untouched).
- `include_ink` returns at most 5,000 points in total; `ink.decimated` and `ink.original_point_count` say whether it was reduced. See `docs/decisions/0003-agent-output-limits.md`.
