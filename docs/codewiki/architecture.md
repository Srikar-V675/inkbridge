# Architecture

```
tablet browser (web/, Excalidraw)  <-- HTTP + WebSocket -->  server/ API (FastAPI + SQLite)
                                                                   ^ HTTP only
                                                  MCP server (server/.../mcp, stdio) <-- Claude Desktop / Code
                                                  vault export skill (calls MCP, writes markdown to the vault)
```

**Rule: the API is the single owner of state.** The MCP server is an HTTP client and must not import `inkbridge.db` (`server/tests/test_mcp_boundary.py`). The backend never writes the vault. Run **one** API process (each process would start its own recognition worker).

## Server modules (`server/src/inkbridge/`)

| Module | Responsibility |
|---|---|
| `api/__init__.py` | App, lifespan (starts the recognition worker, configures logging), `/health`, scene GET/PUT (full or `delta`) |
| `api/chunks.py` | Documents create/list, chunks list, overview, full-size crop |
| `api/regions.py` | Manual regions, crop upload/serve, ink, sketch (pass-1 JSON and marker PNG) |
| `api/ops.py`, `db/ops.py` | Agent ops queue (`agent_ops`); stores `font_size` per op |
| `api/questions.py`, `db/questions.py` | Questions and answers (pull path), publishes `question.update` |
| `api/ws.py` | WebSocket hub: pushes ops/chunk/question events, replays on connect |
| `api/sync.py`, `db/sync.py` | `check_sync` with early cutoff |
| `api/overrides.py` | Manual chunk merge/split (pinned chunks) |
| `api/search.py` | FTS5 search |
| `api/limits.py` | Body-size limits (128 MiB scene; image routes capped separately) |
| `canvas/chunker/` | Pure clustering: union-find proximity, container text, arrows, reading order, kind hint |
| `canvas/hashes.py` | bbox and the three hashes |
| `agent/placement.py` | Server-side placement and font sizing of agent output (gap 40 px; font from median handwriting stroke height, clamp 18..64, default 28; diagrams 600x400 scaled by font) |
| `timing.py` | `timed()` log helper and `RequestTiming` middleware (counts and ms only, never content) |
| `agent/mermaid.py` | Flowchart-only gate (`flowchart`/`graph`) |
| `canvas/sketch.py`, `canvas/sketch_image.py`, `canvas/sketch_prompts.py` | Two-pass sketch-to-diagram: node/arrow guess plus numbered-marker image |
| `recognizer/gemini.py` | Swappable recognizer (decision 0006) |
| `recognizer/worker.py` | Daemon thread, own connection, idle-gated, backs off on failures |
| `db/__init__.py`, `db/outline.py`, `db/migrations/*.sql` | SQLite layer, forward-only migrations 0001..0005 |
| `mcp/server.py`, `mcp/client.py` | MCP tools and prompt; HTTP client |
| `mcp_smoke.py` | `inkbridge-mcp-smoke` stdio client check |

## Key design ideas

1. **Scene** = versioned snapshot of Excalidraw elements per document; `PUT` carries `base_version` (409 on conflict; the browser merges and retries, decision 0008). With `delta: true` the body holds only elements changed since `base_version` and the server merges them by id (decision 0036, [deep dive](../deepdive/4.%20Deep%20Dive/scene-delta-saves.md)).
2. **Chunker runs inside every scene save.** Chunks are `regions` with `created_by='auto'`, with stable ids via greedy element-id Jaccard match (>0.5); splits/merges set `successor_of`; undo reactivates (decision 0011). Tuning constants: `k` 1.5, `arrow_merge` 6.0, `link_reach` 3.0, `match_threshold` 0.5. Optional `INKBRIDGE_CHUNK_CONTAINMENT` (off by default) also keeps an id when that share of a chunk survives (decision 0029). Orphaned chunks are kept forever (decision 0028).
3. **Three hashes** (decision 0005):
   - `stroke_hash`: exact ink incl. ids and position. Drives `png_stale`.
   - `content_hash`: shape of the ink, position as offsets from the bbox origin (0.001 px), no ids. Keys the recognition cache, search index and note provenance.
   - `text_hash`: normalised reading. Drives early cutoff in `check_sync`.
   - Never hash `version`, `versionNonce`, `updated`, `seed`, `customData`.
4. **Recognition is a cache** keyed `(region, content_hash, source)`; precedence `user > agent > gemini`. Moved or unchanged ink never calls a model.
5. **Crops are rendered only in the browser** (`sync/cropSync.ts`): when idle and saved, it uploads PNGs for `png_stale` chunks, answered 409 if the scene moved on (decision 0015).
6. **Agent write-back = drafts.** Ops (`write_text`, `draw_diagram`) are queued server-side, pushed over WebSocket, drawn as dashed elements tagged `customData {author:"agent", draft:true, op_id}`. The text size is computed on the server from the handwriting scale (decision 0032). The user resolves drafts with Accept / Reject / Accept all (`drafts/resolve.ts`, `drafts/DraftBar.tsx`, decision 0026): accept saves first, then PATCHes; reject PATCHes first, then sweeps by id prefix. Mermaid conversion happens only in the browser, so `draw_diagram` waits for the browser ack, then expires on give-up (decision 0023). Drafts are excluded from chunking, recognition and export until accepted.
7. **Questions (pull path).** The browser or any client posts a question; any MCP client lists pending ones and answers (`list_questions`, `answer_question`); no runner starts anything (decision 0035).
8. **Timing logs** (decision 0030). Server: `inkbridge.request`, `inkbridge.scene`, `inkbridge.timing` (>1 s logs a warning). Browser: `lib/timing.ts` records `scene.load`, `scene.save`, `crop.upload`, `crop.pass`; in dev they go to `web/dev.log` via `/__log`.
9. **Vault loop.** The export skill calls `read_canvas`, writes one marker-bounded block per chunk (`<!-- ink:ID hash:H -->` ... `<!-- /ink -->`) plus frontmatter `inkbridge: {canvas, exported, chunks:[{id, hash, reading, section}]}`; re-export rewrites only changed blocks. Format: `docs/vault-note-format.md`.

## Invariants (easy to break)

- User ink is never edited or deleted by an agent path; enforced in `server/` (rejects payloads naming existing element ids; acks must carry the op's `id_prefix`). Test: `server/tests/test_ops_api.py`.
- Hash allow-lists only (see above).
- Drafts are not content.
- MCP stdio: stdout is protocol frames only; never run scripts from inside `mcp/` (it shadows the SDK).
- No generated handwriting strokes; pressure (`pressures`, `simulatePressure=false`) preserved through load/save.
- Recognition never blocks drawing; Gemini free tier trains on content, so only canvases in `INKBRIDGE_RECOGNIZE_DOCUMENTS`.
- The `/__log` Vite endpoint is dev-only.
- No Obsidian plugin, no drawing inside the vault, no cross-canvas links.

## Auth

None. The API is for a trusted LAN. WebSocket checks same-origin. LAN HTTP is not a secure context, so features needing one are out.

## WebSocket events (`WS /ws?document={id}`)

Server to browser: `op.pending`, `op.updated`, `op.error`, `chunks.updated {version, stale_crops}`, `question.update {question}`. Browser to server: `op.applied {op_id, element_ids}`, `op.failed {op_id, error}`. On connect the server replays pending and delivered ops; ops are idempotent by `op_id`.

## Op lifecycle (`agent_ops.status`)

`pending` -> `delivered` (one browser got it) -> `applied` (browser drew it) -> `accepted` / `rejected` (user, via the draft bar); or `failed` / `expired`.

Question lifecycle (`questions.status`): `pending` -> `answered` or `cancelled`; any other move is 409 `invalid_transition`.

## Data ownership

| Entity | Owner |
|---|---|
| Scenes, chunks, regions, recognitions, links, ops, questions | API (SQLite, `INKBRIDGE_DB`) |
| Crop PNGs | `data/crops/<region_id>.png` beside the DB |
| Vault notes | The user's vault, written only by the export skill |
