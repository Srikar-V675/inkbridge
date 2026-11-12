# API reference

FastAPI on `:8000`. The Vite dev server proxies `/documents`, `/ops`, `/regions`, `/search`, `/health`, `/ws` (the API sends no CORS headers); in daily use the API serves the built app itself. Default document id is `default`; the web app selects with `?canvas=<id>`, and `/` is the canvases home.

## HTTP routes

| Method | Path | Source | Purpose |
|---|---|---|---|
| GET | `/health` | `api/__init__.py` | Liveness; reports `crop_source` |
| GET | `/documents/{id}/scene` | `api/__init__.py` | Load live ink `{seq, version, elements}` (`?deleted=true` includes deleted) |
| PUT | `/documents/{id}/scene` | `api/__init__.py` | Legacy save `{base_version, elements, delta?}`; per-element merge with `strict=False`, no 409 for a stale base; 422 over 50,000 elements; re-chunks; `X-Inkbridge-Save` makes it idempotent; the answer carries `timing` |
| GET | `/documents/{id}/elements` | `api/__init__.py` | Changed element rows since `?since=N` |
| POST | `/documents/{id}/elements` | `api/__init__.py` | Save elements, idempotent by `(device, batch)`; refuses draft-flagged elements and new `<op_id>:` ids |
| POST, GET | `/documents` | `api/chunks.py`, `api/canvases.py` | Create canvas; list summaries (hides archived; `?archived=true` or `all`) |
| GET, PATCH | `/documents/{id}` | `api/canvases.py` | One summary; rename, pin, archive, `chunker` (changing it re-chunks at once) |
| POST | `/documents/{id}/duplicate`, `/open` | `api/canvases.py` | Duplicate a canvas; record an open |
| GET | `/documents/{id}/thumbnail` | `api/canvases.py` | 960x640 thumbnail, cached per scene version |
| GET | `/documents/{id}/chunks` | `api/chunks.py` | Chunks in reading order, deep links |
| GET | `/documents/{id}/overview` | `api/chunks.py` | Overview image of the canvas |
| GET | `/regions/{id}/png` | `api/chunks.py` | Full-size stored crop |
| POST | `/documents/{id}/regions` | `api/regions.py` | Create manual region |
| GET | `/documents/{id}/regions` | `api/regions.py` | Manual regions; `?chunks=true` lists chunks |
| GET | `/regions/{id}` | `api/regions.py` | One region/chunk with best reading |
| PUT | `/regions/{id}/image` | `api/regions.py` | Upload crop; 409 if scene version moved on; 403 when `INKBRIDGE_CROP_SOURCE=server` |
| GET | `/regions/{id}/image` | `api/regions.py` | Crop, capped at 1024 px wide by default |
| GET | `/regions/{id}/ink` | `api/regions.py` | Decimated ink (max 5,000 points) |
| GET | `/regions/{id}/sketch`, `/sketch.png` | `api/regions.py` | Sketch pass-1 JSON and marker image |
| POST | `/documents/{id}/chunks/merge`, `/split` | `api/overrides.py` | Pin a merge or split |
| POST | `/documents/{id}/check_sync` | `api/sync.py` | Compare note hashes with live ink |
| GET | `/search` | `api/search.py` | FTS5 search, per canvas |
| GET | `/retrieve` | `api/retrieve.py` | Keyword retrieval over chunk readings and answered questions; `scope=all` crosses canvases |
| GET | `/documents/{id}/graph/subgraph`, `/path`, `/components` | `api/graph.py` | Read-only networkx views over active chunks and arrow links |
| POST | `/documents/{id}/ops`, `/ops` | `api/ops.py` | Enqueue `write_text` or `draw_diagram` |
| GET | `/documents/{id}/ops`, `/ops/{op_id}` | `api/ops.py` | List/read ops |
| PATCH | `/ops/{op_id}` | `api/ops.py` | Status updates (failed, expired, ...) |
| POST | `/ops/{op_id}/accept`, `/reject`, `/unaccept` | `api/ops.py` | Resolve a draft; idempotent; accept writes the elements into the scene in one transaction |
| GET | `/documents/{id}/drafts` | `api/ops.py` | Open drafts of a canvas |
| GET | `/documents/{id}/diagrams/{diagram_id}/markup`, `/markup.png` | `api/markup.py` | Mark-up of a diagram (new ink in red) for `get_markup` |
| GET, PUT | `/documents/{id}/brief` | `api/memory.py` | Per-canvas brief |
| GET | `/documents/{id}/changes` | `api/memory.py` | What changed since the agent last looked |
| GET | `/documents/{id}/tasks` | `api/tasks.py` | Agent tasks |
| POST | `/tasks/{id}/claim`, `/complete` | `api/tasks.py` | Claim or finish a task |
| POST, GET | `/documents/{id}/offers` | `api/offers.py` | Create or list offers |
| POST | `/offers/{id}/tap`, `/dismiss` | `api/offers.py` | Resolve an offer |
| PUT | `/documents/{id}/focus` | `api/offers.py` | Focus toggle |
| POST | `/documents/{id}/watch` | `api/watch.py` | Register note chunks for the `stale_note` detector (nothing calls it yet) |
| POST, PUT | `/debug/device-log`, `/debug/echo` | `api/debug.py` | Only with `INKBRIDGE_DEVICE_LOG=1` |
| GET | `/`, `/assets/*`, `/favicon.svg` | `api/web.py` | The built web app (single origin) |
| WS | `/ws?document=` | `api/ws.py` | Push channel, see [architecture.md](architecture.md) |

### Questions (`api/questions.py`, decisions 0035, 0099)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents/{id}/questions` | Create `{text (1..4000), focus_element_ids (max 200), parent_id?}`; 201; 422 `parent_not_found` |
| GET | `/documents/{id}/questions` | List; `status` filter, `limit` 1..100 (default 20), oldest first |
| GET | `/questions/{id}` | One question with `focus_chunk_ids` (computed now) and `history` (up to 5 ancestors, oldest first) |
| POST | `/questions/{id}/answer` | `{answer_md (1..20000), sources[] (max 50)}`; source is `{type:"chunk", id}` or `{type:"note", path}` |
| POST | `/questions/{id}/cancel` | Cancel a pending question |

Only `pending -> answered|cancelled` is allowed (409 `invalid_transition` with current status). Each create/answer/cancel publishes `question.update` on the canvas WebSocket; streamed partial answers arrive as `question.delta` (`answer_question(final=false)`, migration 0018).

### Logging

`RequestTiming` logs one line per HTTP request (method, route template, status, ms; warning above 1 s). Scene saves log phases under `inkbridge.scene` and return `timing {recv, queue, lock, work, commit, total}`; `inkbridge.loop` logs event-loop lag. No scene content, keys or readings are logged.

Refusals worth knowing: `existing_element_id` (422), `not_flowchart`, `anchor_not_found`, `anchor_gone` (orphaned anchor with no live successor), `bad_ack`, `not_found`, `invalid_transition` (409), `parent_not_found` (422).

## MCP tools (`inkbridge-mcp`, stdio)

Full table with inputs and outputs: `docs/mcp-tools.md`. Canvas tools take and echo `document_id` (default from `INKBRIDGE_DOCUMENT`). Summary:

| Tool | Mutates | Notes |
|---|---|---|
| `read_canvas` | No | Whole canvas in reading order with links and `groups`, the brief, and an overview PNG paged in bands (`max_width`, `offset`); text over 60,000 chars is cut with an `offset` |
| `get_region` | No | One chunk/region: text, crop, optional `include_ink`, `include_sketch`; an orphan returns only a pointer to its live successor |
| `list_regions` | No | Manual regions only |
| `search` | No | Prefix search, ANDed words, text and LaTeX, per canvas |
| `retrieve` | No | Keyword match over chunk readings and answered questions, per canvas or all; vault text is never indexed |
| `get_subgraph`, `canvas_components` | No | networkx views over chunks and arrow links |
| `what_changed` | Cursor with `mark_seen=true` | Chunks the user touched since the agent last looked |
| `set_canvas_brief` | Brief | Write the per-canvas brief |
| `check_sync` | Recognition cache | `fresh`, `fresh_after_reread`, `changed`, `replaced`, `removed`, `new`; waits up to `wait_s` for re-reading |
| `create_canvas` | Adds a document | |
| `write_text` | Adds a draft op | 1 to 10,000 chars, optional chunk `anchor`, optional `size` (`small`/`normal`/`large`); returns `{op_id, status, placement, font_size}` |
| `draw_diagram` | Adds a draft op | Flowchart Mermaid only; waits for the browser ack (default 20 s) |
| `edit_diagram` | Adds a revision draft | Revises a diagram object; Accept replaces only untouched shapes |
| `get_markup` | No | Diagram crop with the user's new ink in red |
| `list_questions` | No | Default `pending`, oldest first, `limit` 1..100; includes `focus_chunk_ids` and `history` |
| `answer_question` | Stores answer text | `answer_md` up to 20,000 chars, `sources[]`; `final=false` streams a partial; error if not pending |
| `list_tasks`, `claim_task`, `complete_task` | Task state | The agent task queue |
| prompt `sketch_to_diagram` | n/a | `mode=two_pass` (default) or `one_shot` |
