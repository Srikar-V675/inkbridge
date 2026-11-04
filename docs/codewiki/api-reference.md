# API reference

FastAPI on `:8000`. The dev server proxies `/documents`, `/ops`, `/regions`, `/search`, `/health`, `/ws` (the API sends no CORS headers). Default document id is `default`; the web app selects with `?canvas=<id>`.

## HTTP routes

| Method | Path | Source | Purpose |
|---|---|---|---|
| GET | `/health` | `api/__init__.py` | Liveness |
| GET | `/documents/{id}/scene` | `api/__init__.py` | Load scene `{version, elements}` |
| PUT | `/documents/{id}/scene` | `api/__init__.py` | Save `{base_version, elements, delta?}`; 409 `{current_version}` on conflict; 422 over 50,000 elements; re-chunks on save. `delta: true` = `elements` holds only changed elements, merged by id (decision 0036) |
| POST | `/documents` | `api/chunks.py` | Create canvas |
| GET | `/documents` | `api/chunks.py` | List canvases |
| GET | `/documents/{id}/chunks` | `api/chunks.py` | Chunks in reading order, deep links |
| GET | `/documents/{id}/overview` | `api/chunks.py` | Overview image of the canvas |
| GET | `/regions/{id}/png` | `api/chunks.py` | Full-size stored crop |
| POST | `/documents/{id}/regions` | `api/regions.py` | Create manual region |
| GET | `/documents/{id}/regions` | `api/regions.py` | Manual regions; `?chunks=true` lists chunks |
| GET | `/regions/{id}` | `api/regions.py` | One region/chunk with best reading |
| PUT | `/regions/{id}/image` | `api/regions.py` | Upload crop; 409 if scene version moved on |
| GET | `/regions/{id}/image` | `api/regions.py` | Crop, capped at 1024 px wide by default |
| GET | `/regions/{id}/ink` | `api/regions.py` | Decimated ink (max 5,000 points) |
| GET | `/regions/{id}/sketch` | `api/regions.py` | Sketch pass-1 JSON (nodes, arrows, unattached, markers) |
| GET | `/regions/{id}/sketch.png` | `api/regions.py` | Marker image |
| POST | `/documents/{id}/chunks/merge` | `api/overrides.py` | Pin a merge of chunks |
| POST | `/documents/{id}/chunks/split` | `api/overrides.py` | Pin a split |
| POST | `/documents/{id}/check_sync` | `api/sync.py` | Compare note hashes with live ink |
| GET | `/search` | `api/search.py` | FTS5 search, per canvas |
| POST | `/documents/{id}/ops`, `/ops` | `api/ops.py` | Enqueue `write_text` or `draw_diagram` |
| GET | `/documents/{id}/ops`, `/ops/{op_id}` | `api/ops.py` | List/read ops |
| PATCH | `/ops/{op_id}` | `api/ops.py` | Status: applied, failed, expired, accepted, rejected (+`element_ids`, `error`) |
| WS | `/ws?document=` | `api/ws.py` | Push channel, see [architecture.md](architecture.md) |

### Questions (`api/questions.py`, decision 0035)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents/{id}/questions` | Create `{text (1..4000), focus_element_ids (max 200), parent_id?}`; 201; 422 `parent_not_found` |
| GET | `/documents/{id}/questions` | List; `status` filter, `limit` 1..100 (default 20), oldest first |
| GET | `/questions/{id}` | One question with `focus_chunk_ids` (computed now) and `history` (up to 5 ancestors, oldest first) |
| POST | `/questions/{id}/answer` | `{answer_md (1..20000), sources[] (max 50)}`; source is `{type:"chunk", id}` or `{type:"note", path}` |
| POST | `/questions/{id}/cancel` | Cancel a pending question |

Only `pending -> answered|cancelled` is allowed (409 `invalid_transition` with current status). Each create/answer/cancel publishes `question.update` on the canvas WebSocket.

### Logging

`RequestTiming` logs one line per HTTP request (method, route template, status, ms; warning above 1 s). Scene saves log phases (`parse`, `diff`, `refresh`, `chunks`, `total`) under `inkbridge.scene`. No scene content, keys or readings are logged.

Refusals worth knowing: `existing_element_id` (422), `not_flowchart`, `anchor_not_found`, `bad_ack`, `not_found`, `invalid_transition` (409), `parent_not_found` (422).

## MCP tools (`inkbridge-mcp`, stdio)

Full table with inputs and outputs: `docs/mcp-tools.md`. Summary:

| Tool | Mutates | Notes |
|---|---|---|
| `read_canvas` | No | Whole canvas in reading order + overview PNG; text over 60,000 chars is cut with an `offset` to continue |
| `get_region` | No | One chunk/region: text, crop, optional `include_ink`, `include_sketch` |
| `list_regions` | No | Manual regions only |
| `search` | No | Prefix search, ANDed words, text and LaTeX |
| `check_sync` | Recognition cache | `fresh`, `fresh_after_reread`, `changed`, `replaced`, `removed`, `new`; waits up to `wait_s` for re-reading |
| `create_canvas` | Adds a document | |
| `write_text` | Adds a draft op | 1 to 10,000 chars, optional chunk `anchor`, optional `size` (`small`/`normal`/`large`); returns `{op_id, status, placement, font_size}` |
| `draw_diagram` | Adds a draft op | Flowchart Mermaid only; waits for the browser ack (default 20 s); font size computed like `write_text` |
| `list_questions` | No | Default `pending`, oldest first, `limit` 1..100; includes `focus_chunk_ids` and `history` |
| `answer_question` | Stores answer text | `answer_md` up to 20,000 chars, `sources[]`; error if not pending |
| prompt `sketch_to_diagram` | n/a | `mode=two_pass` (default) or `one_shot` |

Stretch (planned): `get_subgraph` (INK-060).
