# Architecture

```
tablet browser (web/, Excalidraw)  <-- HTTP + WebSocket -->  server/ API (FastAPI + SQLite)
                                                                   ^ HTTP only
                                                  MCP server (server/.../mcp, stdio) <-- Claude Desktop / Code
                                                  vault export skill (calls MCP, writes markdown to the vault)
                                                  optional runner (claude -p per task) <-- INKBRIDGE_RUNNER
```

**Rule: the API is the single owner of state.** The MCP server is an HTTP client and must not import `inkbridge.db` (`server/tests/test_mcp_boundary.py`). The backend never writes the vault. Run **one** API process (each process would start its own recognition worker).

## Server modules (`server/src/inkbridge/`)

| Module | Responsibility |
|---|---|
| `api/__init__.py` | App, lifespan (starts the recognition worker, configures logging), `/health`, scene GET/PUT, `GET`/`POST /documents/{id}/elements` |
| `api/chunks.py`, `api/canvases.py` | Documents create/list, chunks list, overview, full-size crop; canvases home (get, patch, duplicate, open, thumbnail) |
| `api/regions.py`, `api/overrides.py` | Manual regions, crop upload/serve, ink, sketch; manual chunk merge/split (pinned chunks) |
| `api/ops.py`, `db/ops.py`, `db/drafts.py` | Agent ops queue (`agent_ops`); drafts live in the op row; accept, reject, unaccept |
| `api/questions.py`, `api/tasks.py`, `db/questions.py`, `db/tasks.py` | Questions and answers (pull path), streaming `partial_answer`; agent tasks with claim/complete |
| `api/offers.py`, `api/watch.py`, `agent/detectors.py`, `agent/latest_ink.py`, `agent/attention.py` | Proactive offers (off by default, `INKBRIDGE_OFFERS`) |
| `api/memory.py`, `db/memory.py` | Per-canvas brief and `what_changed` |
| `api/markup.py`, `db/diagrams.py`, `agent/markup.py` | Diagram objects and mark-up as instruction |
| `api/graph.py`, `canvas/graph.py` | Read-only networkx subgraph, path, components |
| `api/retrieve.py`, `db/retrieve.py` | Keyword retrieval over chunk readings and answered questions, per canvas or all |
| `api/ws.py` | WebSocket hub: pushes ops, chunk, question, scene, offer and activity events, replays on connect |
| `api/sync.py`, `db/sync.py` | `check_sync` with early cutoff |
| `api/web.py`, `api/debug.py`, `api/limits.py` | Serves the built app; flag-gated device log; body-size limits |
| `db/elements.py`, `db/scenes.py` | Per-element scene rows and merge (`scene_elements`) |
| `canvas/chunker/` | Pure clustering: v1 (`clustering`, `scene`) and v2 (`lines`, `connectors`, `scene_v2`), oversized-chunk cut (`split`), id matching (`matching`), reading order (`order`) |
| `canvas/strokes.py` | Stroke-kind classifier: writing, container, connector, head, underline, scribble |
| `canvas/structure.py` | Plain-words hint of the boxes and arrows in a chunk, handed to the reader |
| `canvas/hashes.py`, `canvas/raster.py`, `canvas/thumb_focus.py` | bbox and the three hashes; Pillow renderer for crops and thumbnails; thumbnail centre chunk |
| `agent/placement.py` | Server-side placement and font sizing of agent output (candidate-spot search; font from the handwriting scale, decision 0094) |
| `agent/ask_runner.py`, `agent/answer_stream.py`, `agent/flow.py` | Runner adapter by task mode; streamed answers; answer placed under its anchor with a flow arrow |
| `canvas_context.py` | `CANVAS_CONTEXT`: what every agent is told about being inside a handwritten canvas (decision 0122) |
| `agent/mermaid.py`, `agent/diagram_ir.py` | Flowchart-only gate; diagram intermediate form |
| `canvas/sketch.py`, `canvas/sketch_image.py`, `canvas/sketch_prompts.py` | Two-pass sketch-to-diagram: node/arrow guess plus numbered-marker image |
| `recognizer/gemini.py`, `recognizer/claude.py`, `recognizer/worker.py` | Swappable readers (decision 0006, 0104); daemon worker thread with its own connection, idle-gated, backs off on failures |
| `timing.py` | `timed()` log helper and `RequestTiming` middleware (counts and ms only, never content) |
| `db/migrations/*.sql`, `db/migrations.py` | SQLite layer, forward-only migrations 0001..0018 |
| `mcp/app.py`, `mcp/client.py`, `mcp/tools/`, `mcp/server.py` | MCP server, HTTP client, one module per tool area, entry point |
| `mcp_smoke.py` | `inkbridge-mcp-smoke` stdio client check |

## Key design ideas

1. **Scene = per-element rows.** Each Excalidraw element is a `scene_elements` row (id, `pos`, `seq`, `version`, nonce, `is_deleted`, JSON). A save merges per element: higher `version` wins, a tie goes to the lower `versionNonce`, nothing is deleted by omission, so there is no 409 (decision 0080). `POST /documents/{id}/elements` is idempotent by `(device, batch)`; the legacy `PUT /scene` runs the same merge with `strict=False`. `GET /scene` returns live ink as `{seq, version, elements}`; `GET /elements?since=N` returns changed rows. Deleted rows keep their JSON 14 days, then shrink to an id stub (decision 0077). The browser writes ink to an IndexedDB journal first and an overlapping sender uploads it; the server pushes `scene.delta` to every device but the writer (decisions 0087, 0088).
2. **Chunker runs inside every scene save.** v2 is the default (decision 0110; `INKBRIDGE_CHUNKER=v1` or a per-canvas `chunker` setting overrides). Strokes get a kind, writing is grouped into lines and ideas, a connector with a free end becomes a `kind: connector` chunk that is never read, and a chunk over the size caps is cut at its widest gaps (`split.py`: 3000 units, 600 elements; decision 0124). Chunks are `regions` with `created_by='auto'` and stable ids via greedy element-id Jaccard match (`match_threshold` 0.5); splits/merges set `successor_of`; undo reactivates (decision 0011). Optional `INKBRIDGE_CHUNK_CONTAINMENT` also keeps an id when that share of a chunk survives (decision 0029). Orphaned auto chunks are collected on save (newest 40, at most 14 days, successor chains kept; decision 0048).
3. **Three hashes** (decision 0005):
   - `stroke_hash`: exact ink incl. ids and position. Drives `png_stale`.
   - `content_hash`: shape of the ink, position as offsets from the bbox origin (0.001 px), no ids. Keys the recognition cache, search index and note provenance.
   - `text_hash`: normalised reading. Drives early cutoff in `check_sync`.
   - Never hash `version`, `versionNonce`, `updated`, `seed`, `customData`.
4. **Recognition is a cache** keyed `(region, content_hash, source)`; precedence `user > agent > gemini`. Moved or unchanged ink never calls a model. The worker (opt-in per canvas) picks Gemini or the persistent Claude Haiku session by `INKBRIDGE_RECOGNIZER`, reads newest-touched chunks first, and for a chunk that looks like a diagram hands the reader the boxes and arrows the server found (`canvas/structure.py`, decision 0123). A `too_large` chunk is never read (decision 0052).
5. **Crops** are rendered in the browser by default (`sync/cropSync.ts`: when idle and saved, one stale chunk per idle slot, 409 if the scene moved on, decision 0015); with `INKBRIDGE_CROP_SOURCE=server` Pillow renders them (`canvas/raster.py`, decision 0065).
6. **Agent write-back = drafts in the op row.** Ops (`write_text`, `draw_diagram`, revisions from `edit_diagram`) are queued server-side and pushed over WebSocket. The browser draws them from its draft store as dashed elements tagged `customData {author:"agent", draft:true, op_id}`, measures them (`op.measured`), and the server places them (`op.placed`, decision 0094). Drafts are never in the scene, the device journal, the live delta or a save, and `POST /elements` refuses draft-flagged elements and new `<op_id>:` ids (decisions 0086, 0090). `POST /ops/{id}/accept|reject|unaccept` are idempotent; accept is one server transaction that writes the elements into `scene_elements` and publishes `scene.delta`. Accepted agent ink is its own chunk with an `agent` reading, never sent to a reader (decision 0044). Text is sized from the handwriting and wrapped at a server-set `wrap_chars` (decisions 0045, 0094). `draw_diagram` waits for the browser ack, then expires on give-up (decision 0023). Diagrams are objects with versions; `edit_diagram` makes a revision whose Accept replaces only untouched shapes (decision 0100); the mark-up flow lets an agent read the diagram crop with the new ink in red (`get_markup`, decision 0102).
7. **Questions and tasks.** The Ask panel or any client posts a question; a task row is created (`agent_tasks`, kinds question, offer, revise, brief). Pull path: any MCP client calls `list_questions` / `answer_question`, or `list_tasks` / `claim_task` / `complete_task`. Push path: with `INKBRIDGE_RUNNER=claude` the runner starts `claude -p` per task, limited to the tools of the task's mode, capped by `INKBRIDGE_AGENT_DAILY_TASKS` (questions exempt). Answers stream through `partial_answer` and `question.delta` (decision 0099). Every runner prompt and the MCP server instructions carry `CANVAS_CONTEXT` (decision 0122); MCP tools take and echo `document_id` (decision 0108).
8. **Offers** (built, off by default, decision 0121): an `offers` table with a budget of 3, mute after 2 dismissals, an attention gate, no-model detectors and a latest-ink read of the newest cluster. `INKBRIDGE_OFFERS=1` turns them on.
9. **Timing logs** (decision 0030). Server: `inkbridge.request`, `inkbridge.scene`, `inkbridge.timing`, `inkbridge.loop`, `inkbridge.recognizer.usage`. Browser: `lib/timing.ts`; with `INKBRIDGE_DEVICE_LOG=1` the device log writes counts and ms to `data/logs/device.jsonl`.
10. **Vault loop.** The export skill calls `read_canvas`, writes one marker-bounded block per chunk (`<!-- ink:ID hash:H -->` ... `<!-- /ink -->`) plus frontmatter `inkbridge: {canvas, exported, chunks:[{id, hash, body, reading, section}]}`; re-export rewrites only changed blocks and adds a conflict callout when the user edited one. Format: `docs/vault-note-format.md`.

## Invariants (easy to break)

- User ink is never edited or deleted by an agent path; enforced in `server/` (rejects payloads naming existing element ids; acks must carry the op's `id_prefix`). Test: `server/tests/test_ops_api.py`.
- Hash allow-lists only (see above).
- Drafts are not content and are not in the scene until Accept.
- MCP stdio: stdout is protocol frames only; never run scripts from inside `mcp/` (it shadows the SDK).
- No generated handwriting strokes; pressure (`pressures`, `simulatePressure=false`) preserved through load/save.
- Recognition never blocks drawing; Gemini free tier trains on content, so only canvases in `INKBRIDGE_RECOGNIZE_DOCUMENTS`; the Claude reader does not train on content.
- The `/__log` Vite endpoint is dev-only.
- No Obsidian plugin, no drawing inside the vault, no cross-canvas links.
- Lime `#D4F23A` in the UI means the agent and only the agent (`DESIGN.md`).

## Auth

None. The API is for a trusted LAN. WebSocket checks same-origin. LAN HTTP is not a secure context; `make serve-https` provides one for the tablet.

## WebSocket events (`WS /ws?document={id}`)

Server to browser: `op.pending`, `op.placed`, `op.updated`, `op.error`, `chunks.updated {version, stale_crops}`, `scene.delta {seq, origin, elements}`, `question.update`, `question.delta`, `offer.created`, `offer.updated` (only while the attention gate is open), `agent.activity {working, what, count}` (the working dot). Browser to server: `attention {pen, view}`, `op.measured {op_id, elements, width, height}`, `op.failed {op_id, error}`. On connect the server replays pending and delivered ops (and placed ops follow as `op.placed`); ops are idempotent by `op_id`.

## Op lifecycle (`agent_ops.status`)

`pending` -> `delivered` (one browser got it) -> `placed` (server placed the measured draft) -> `accepted` / `rejected` (user); or `failed` / `expired`. `accepted` can go back to `placed` (unaccept). Pending and delivered ops expire after 24 h (decision 0049).

Question lifecycle (`questions.status`): `pending` -> `answered` or `cancelled`; any other move is 409 `invalid_transition`. Task lifecycle (`agent_tasks.status`): `pending` -> `running` -> `done` / `failed` / `cancelled`.

## Data ownership

| Entity | Owner |
|---|---|
| Scenes (element rows), chunks, regions, recognitions, links, ops and drafts, questions, tasks, offers, diagrams, brief | API (SQLite, `INKBRIDGE_DB`) |
| Crop PNGs | `data/crops/<region_id>.png` beside the DB |
| Vault notes | The user's vault, written only by the export skill |
