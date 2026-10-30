# Deep Dive: MCP server and client (`server/src/inkbridge/mcp/`, `mcp_smoke.py`)

A stdio MCP server built on the MCP Python SDK 2.x (`MCPServer`, imported from `mcp.server.mcpserver`, `server.py:13`). Entry points in `pyproject.toml`: `inkbridge-mcp = inkbridge.mcp.server:main`, `inkbridge-mcp-smoke`. Tool reference table: `docs/mcp-tools.md`.

## Rules

- **Thin HTTP client**: it never imports `inkbridge.db` (`tests/test_mcp_boundary.py`). All state goes through `ApiClient`.
- **stdout carries protocol frames only**; logging goes to stderr (`main()`: `logging.basicConfig(stream=sys.stderr)`). SDK 2.x also diverts stray `sys.stdout` writes to stderr (SDK issue #1933); the raw-stdout test in `test_mcp_smoke.py` guards it end to end.
- The package directory is named `mcp`, so never run a script from inside it: it shadows the SDK. Use the entry point or `python -m inkbridge.mcp`.
- Errors are `ToolError` with a next step the agent can act on.

## ApiClient (`client.py`)

- `base_url` from `INKBRIDGE_API_URL` (default `http://127.0.0.1:8000`), timeout 30 s; default canvas from `INKBRIDGE_DOCUMENT`. A passed-in `http` client (tests) is not closed by `close()`.
- Error classes: `ApiError`; `NotFound` (404); `Conflict` (409). Status handling is by status code rather than `raise_for_status()` because the error class differs between httpx builds (Starlette's TestClient ships its own); any non-2xx, including an unfollowed 3xx, is an `ApiError`.
- `_get` messages: unreachable API -> "Is `make dev-server` running, and is INKBRIDGE_API_URL correct?"; 404 -> "Not found: <path>. <hint>" with `NO_REGION` ("Call list_regions or read_canvas...") or `NO_CANVAS`.
- `_post` (used by `check_sync`) maps 422 to a hint about chunk id and hash; `timeout=wait_s + 30` gives the call room beyond the server's wait.
- `_send` (create_op, set_op_status, create_document) surfaces the API's own `detail.msg` (cut to 500 chars) on 404/409/422.
- Methods: `list_regions`, `get_region`, `get_image`, `get_ink`, `search`, `get_chunks`, `get_overview`, `check_sync`, `create_op`, `get_op`, `set_op_status`, `get_sketch`, `get_sketch_image`, `create_document`. All path parts are `quote(..., safe="")`.

## Tools (`server.py`)

| Tool | Behaviour |
|---|---|
| `list_regions` | Manual regions only; id, kind, bounds, stroke_count, 80-character preview, updated_at |
| `get_region(region_id, include_image=True, include_ink=False, include_sketch=False)` | JSON metadata (`id, kind, text, latex, source, bounds, status, png_stale, updated_at`) + optional `ink`/`sketch` + PNG as `Image` content. A missing crop returns a text note instead of failing: 404 -> "the crop file is missing"; other errors name the real cause. Marker image failure also becomes a note |
| `read_canvas(document_id?, include_overview=True, offset=0)` | Chunks in reading order as compact JSON + overview PNG |
| `search(query, limit=10, document_id?)` | Prefix FTS results |
| `check_sync(chunks[{id, hash, reading?}], document_id?, wait_s=15)` | Pass-through to the API; `NotFound` -> "Unknown canvas ..." |
| `write_text(text, anchor?, document_id?)` | Enqueues a `write_text` op; returns `{op_id, status, placement}`; does not wait |
| `create_canvas(title)` | Returns `{document_id, url}` |
| `draw_diagram(mermaid, anchor?, document_id?, wait_seconds=20)` | Enqueue, poll until applied, expire on give-up |
| prompt `sketch_to_diagram(region_id, mode="two_pass")` | Text from `sketch_prompts.sketch_prompt` |

### `read_canvas` size control (`:216-317`)

The outline JSON never exceeds `READ_CANVAS_MAX_CHARS = 60_000` (about 15k tokens). `_outline_chunk` keeps only `_OUTLINE_FIELDS` (id, order, kind, bounds, text, latex, status, png_stale, content_hash, text_hash, links, deep_link), cuts a reading over `MAX_READING_CHARS = 4_000` with `…` and sets `text_truncated`/`latex_truncated`, and keeps at most `MAX_LINKS = 20` links with `links_omitted`. `_fit` computes room for the head plus the longest possible note, adds chunks until the cap, and sets `omitted` plus a note naming the next `offset`. Because each chunk is bounded, at least one always fits, so the offset always advances. JSON is compact (`separators=(",", ":")`), because a model reads it and indentation only costs tokens. The overview image failing becomes a text note.

### `draw_diagram` flow (`:359-435`)

`create_op` -> `_wait_for_browser` polls `GET /ops/{id}` every `POLL_SECONDS = 0.25` while the status is pending or delivered until the deadline. On give-up it `PATCH`es the op to `expired` (a late browser sweeps expired ops and never draws them); a `Conflict` there means the browser finished just now, so it re-reads the op. Outcomes: `applied` returns `{op_id, status, element_count}`; `failed` raises a ToolError with the browser's message and "Fix the Mermaid (flowchart syntax only)"; `expired` says no browser drew it in N s and gives the canvas URL; anything else raises. `_sleep`/`_clock` are module-level so tests replace them.

## Smoke tool (`mcp_smoke.py`)

`inkbridge-mcp-smoke --api <url>` drives `inkbridge-mcp` over stdio with the MCP SDK's own client: `initialize`, `tools/list`, `read_canvas`, `get_region` on the first chunk, `search`, and an unknown canvas; prints PASS/FAIL per check and exits 1 on failure; read-only. SDK 2.x client uses snake_case `mime_type`/`is_error`, not the wire names.

### Smoke details (`mcp_smoke.py`, 110 lines)

Starts `python -m inkbridge.mcp` as a subprocess with `INKBRIDGE_API_URL` and `INKBRIDGE_DOCUMENT` in its environment, using the SDK's `stdio_client` and `ClientSession`; whole run bounded by `TIMEOUT_S = 60`. A `Report` collects `(name, ok, detail)` checks. Checks: `tools/list` contains `EXPECTED_TOOLS = {list_regions, get_region, search, read_canvas}` (it does not require the newer tools); `read_canvas` is a text block first and not an error; the outline has `chunk_count` and `chunks`; the second block is an `image/png` whose base64 decodes to bytes starting with the PNG signature; `get_region` on the first chunk returns exactly two blocks (text, then crop or a note) with a matching `id` (skipped if the canvas has no chunks); `search` returns text only; an unknown canvas is a tool error (`is_error`). Any exception talking MCP becomes one failed `mcp session` check. Prints PASS/FAIL lines, exit status 0 only if every check passed.

## Client setup

Claude Code: `claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp`. Claude Desktop config in `docs/mcp-tools.md`. How the GUIs render image content is not yet verified (decision 0003 still has a "?").

## Testing

`test_mcp_tools.py`, `test_mcp_read_canvas.py`, `test_mcp_write_text.py`, `test_mcp_draw_diagram.py`, `test_mcp_sketch.py`, `test_mcp_smoke.py`, `test_mcp_boundary.py`.

## Potential improvements

`list_regions` lists only manual regions, which can surprise a caller expecting chunks (`read_canvas` is the chunk listing). `list_questions`/`answer_question` are planned (INK-047).
