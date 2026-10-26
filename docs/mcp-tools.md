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
| `create_canvas` | `title` (1 to 200 chars) | JSON `{document_id, url}`; `url` opens the new, empty canvas | Adds a document (never changes an existing one) |
| `draw_diagram` | `mermaid` (flowchart only), `anchor?` (chunk id), `document_id?`, `wait_seconds=20` (1 to 60) | JSON `{op_id, status: "applied", element_count}` once the browser has drawn the dashed drafts | Adds a draft op (never edits ink) |
| `get_region` | `region_id`, `include_image=true`, `include_ink=false`, `include_sketch=false` | JSON text `{id, kind, text, latex, source, bounds, status, png_stale, updated_at, ink?, sketch?}` plus the region PNG as image content; with `include_sketch`, also the marker image | No |
| `write_text` | `text` (1 to 10,000 chars), `anchor?` (chunk id), `document_id?` | JSON `{op_id, status: "pending", placement: {x, y}}`; the text appears as a dashed draft in any open browser, now or when the canvas is next opened | Adds a draft op (never edits ink) |
| `search` | `query`, `limit=10` | JSON `{results: [{region_id, snippet, score}]}`; snippet marks matches with `[ ]`; score is higher-is-better (negated BM25) | No |

Search is prefix-based, ANDs the words, covers text and LaTeX, and only returns active regions. The index holds the best reading (user > agent > gemini) for the region's current ink, keyed by its position-independent content hash: changing the ink drops its old text until it is re-recognised, while moving it keeps the reading and the search hit.

Errors are returned as tool errors with a next step (for example, "call list_regions to see valid region ids").

**Sketch to diagram** (two-pass reading, INK-058, decision [0018](decisions/0018-sketch-two-pass.md)):
- `get_region(include_sketch=true)` adds a `sketch` field, the server's pass-1 guess from the ink alone with no model call:
  - `nodes`: `[{id: N1.., box, element_ids, label_element_ids, label_text, confidence}]`
  - `arrows`: `[{id: A1.., from, to, head: "end"|"both"|null, tip, tail, element_ids, confidence}]`
  - `unattached`: strokes that touch fewer than two nodes
  - `markers`: pixel positions on the marker image

  It also adds a second image: the ink redrawn with red node markers on node centres, blue arrow markers on arrow tips, and grey markers (U1..) on unattached strokes.
- The read follows arrow `links` one hop, so a flowchart split into one chunk per node still resolves its arrows. Drafts are left out.
- The MCP prompt `sketch_to_diagram(region_id, mode)` gives the instructions. With `mode=two_pass` (default), the agent checks the guess, writes Mermaid that uses the marker ids, flags uncertain arrows, then calls `draw_diagram` anchored beside the sketch. With `mode=one_shot`, it uses the crop alone. INK-053's E2 experiment compares the two.

`draw_diagram` needs the canvas open in a browser, because Mermaid is converted there (decision [0017](decisions/0017-draw-diagram-wait.md)). The API refuses anything that is not a flowchart (`flowchart` / `graph`): sequence, class and other diagram types would come back as one uneditable image. The tool polls the op until the browser acks it, for up to `wait_seconds`. Its errors are:
- `Mermaid could not be parsed: <message>`, reported by the browser. No elements are drawn.
- `No browser drew the diagram within N s … Open the canvas at <url>`. The op is set to `expired`, so a browser that connects later never draws it.
- The API's own refusals: `not_flowchart`, `anchor_not_found`, `existing_element_id`.

## Planned tools (spec v3)

Not built yet; each ticket updates this file when it lands. All tools take an optional `document_id` (default `INKBRIDGE_DOCUMENT`).

| Tool | Ticket | Purpose | Mutates |
|---|---|---|---|
| `read_canvas` | INK-034 | Whole-canvas outline in reading order: chunks with text, kind, bounds, links, `content_hash`, `deep_link`, plus an overview image. `search` also gains `document_id`. | No |
| `check_sync` | INK-036 | Given `[{id, hash, reading}]` from a note's frontmatter, returns `fresh`, `fresh_after_reread`, `changed`, `replaced` (with successor), `removed`, `new`. May fill the recognition cache. | Cache only |
| `list_questions` | INK-047 | Pending Ask AI questions with focus chunks and history (the vendor-neutral pull path). | No |
| `answer_question` | INK-047 | Store a markdown answer and sources for a question. | Questions table |

Outside MCP: `GET /regions/{id}/sketch` (pass-1 JSON) and `GET /regions/{id}/sketch.png` (marker image) back `include_sketch`. `GET /regions/{id}/png` serves a chunk's stored crop at full size (built, INK-033; the `GET /regions/{id}/image` is capped at 1024 px wide by default) so the export skill can save it into the vault. `save_transcription` and `get_neighbors` from the v1 plan are dropped.

## Limits

- Images are downscaled to at most 1024 px wide (API default; the stored crop is untouched).
- `include_ink` returns at most 5,000 points in total; `ink.decimated` and `ink.original_point_count` say whether it was reduced. See `docs/decisions/0003-agent-output-limits.md`.

`png_stale: true` means the ink changed since the crop was saved, so the image may not match the strokes. Ink strokes carry `x`, `y` and `angle`; their `points` are relative to `(x, y)`. If the image cannot be fetched, `get_region` still returns the transcription plus a note: "the crop file is missing" only when the API answers 404, otherwise the actual error (retry those).
