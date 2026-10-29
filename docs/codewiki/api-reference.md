# API reference

FastAPI on `:8000`. The dev server proxies `/documents`, `/ops`, `/regions`, `/search`, `/health`, `/ws` (the API sends no CORS headers). Default document id is `default`; the web app selects with `?canvas=<id>`.

## HTTP routes

| Method | Path | Source | Purpose |
|---|---|---|---|
| GET | `/health` | `api/__init__.py` | Liveness |
| GET | `/documents/{id}/scene` | `api/__init__.py` | Load scene `{version, elements}` |
| PUT | `/documents/{id}/scene` | `api/__init__.py` | Save with `base_version`; 409 on conflict; re-chunks on save |
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

Planned (INK-047): `POST/GET /documents/{id}/questions`, `GET /questions/{id}`, `POST /questions/{id}/answer`, `POST /questions/{id}/cancel`.

Refusals worth knowing: `existing_element_id` (422), `not_flowchart`, `anchor_not_found`, `bad_ack`, `not_found`.

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
| `write_text` | Adds a draft op | 1 to 10,000 chars, optional chunk `anchor` |
| `draw_diagram` | Adds a draft op | Flowchart Mermaid only; waits for the browser ack (default 20 s) |
| prompt `sketch_to_diagram` | n/a | `mode=two_pass` (default) or `one_shot` |

Planned: `list_questions`, `answer_question` (INK-047); stretch `get_subgraph` (INK-060).
