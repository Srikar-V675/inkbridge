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

## Tools (built)

| Tool | Input | Returns | Mutates |
|---|---|---|---|
| `list_regions` | `document_id?`, `kind?`, `limit=50` | JSON `{regions: [{id, kind, bounds, stroke_count, preview, updated_at}]}` | No |
| `get_region` | `region_id`, `include_image=true`, `include_ink=false` | JSON text `{id, kind, text, latex, source, bounds, status, png_stale, updated_at, ink?}` plus the region PNG as image content | No |
| `search` | `query`, `limit=10` | JSON `{results: [{region_id, snippet, score}]}`; snippet marks matches with `[ ]`; score is higher-is-better (negated BM25) | No |

Search is prefix-based, ANDs the words, covers text and LaTeX, and only returns active regions. The index holds the best reading (user > agent > gemini) for the region's current ink, keyed by its position-independent content hash: changing the ink drops its old text until it is re-recognised, while moving it keeps the reading and the search hit.

Errors are returned as tool errors with a next step (for example, "call list_regions to see valid region ids").

## Planned tools (spec v3)

Not built yet; each ticket updates this file when it lands. All tools take an optional `document_id` (default `INKBRIDGE_DOCUMENT`).

| Tool | Ticket | Purpose | Mutates |
|---|---|---|---|
| `read_canvas` | INK-034 | Whole-canvas outline in reading order: chunks with text, kind, bounds, links, `content_hash`, `deep_link`, plus an overview image. `search` also gains `document_id`. | No |
| `check_sync` | INK-036 | Given `[{id, hash, reading}]` from a note's frontmatter, returns `fresh`, `fresh_after_reread`, `changed`, `replaced` (with successor), `removed`, `new`. May fill the recognition cache. | Cache only |
| `list_questions` | INK-047 | Pending Ask AI questions with focus chunks and history (the vendor-neutral pull path). | No |
| `answer_question` | INK-047 | Store a markdown answer and sources for a question. | Questions table |
| `create_canvas` | INK-043 | New empty canvas, returns `{document_id, url}`. | Adds a document |
| `write_text` | INK-043 | Draft text near an anchor chunk, or in free space; arrives as a draft. | Adds a draft op |
| `draw_diagram` | INK-044 | Draft a Mermaid flowchart (browser converts and acknowledges; the browser must be open). | Adds a draft op |

Outside MCP: `GET /regions/{id}/png` serves a chunk's stored crop at full size (built, INK-033; the `GET /regions/{id}/image` is capped at 1024 px wide by default) so the export skill can save it into the vault. `save_transcription` and `get_neighbors` from the v1 plan are dropped.

## Limits

- Images are downscaled to at most 1024 px wide (API default; the stored crop is untouched).
- `include_ink` returns at most 5,000 points in total; `ink.decimated` and `ink.original_point_count` say whether it was reduced. See `docs/decisions/0003-agent-output-limits.md`.

`png_stale: true` means the ink changed since the crop was saved, so the image may not match the strokes. Ink strokes carry `x`, `y` and `angle`; their `points` are relative to `(x, y)`. If the image cannot be fetched, `get_region` still returns the transcription plus a note: "the crop file is missing" only when the API answers 404, otherwise the actual error (retry those).
