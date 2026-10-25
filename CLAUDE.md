# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Inkbridge is a handwritten canvas (Excalidraw) wired into a markdown vault. In the v3 design the server groups ink into addressable **chunks**, and MCP agents read the whole canvas, write vault notes that trace back to the ink, answer questions, and draw back as drafts the user accepts or rejects. Much of this is still planned; the architecture bullets below say which parts are built.

Spec of record: **spec v3 (final, 23 Oct 2026)** https://claude.ai/artifact/FkyFV1UySxqfC9oFEYb1P1. How it works (schema, hashes, chunker, API, flows): **technical reference v3** https://claude.ai/artifact/1uMmVHEyuvb2uS5Dgutaqy. `docs/project-doc.html` is the v1 draft, kept as history only. Work is planned as numbered tickets (`INK-xxx`) in `docs/tickets/`, which is local and gitignored; read `docs/tickets/README.md` before starting a task. Build by 27 Oct 2026, submit 28 Oct.

## Commands

```bash
make install          # uv sync (server) + npm install (web)
make dev-server       # FastAPI on :8000 (reload)
make dev-web          # Vite on :5173, --host so the tablet can reach it
make test             # server pytest
make lint             # ruff + oxlint + tsc -b
```

- Single server test: `cd server && uv run pytest tests/test_health.py::test_health`
- Web: `npm test` runs framework-free logic tests with Node's built-in runner (`web/tests/`, no extra dependency); other checks are `npm run lint`, `npx tsc -b`, `npm run build` (run in `web/`). The dev server proxies `/documents`, `/regions`, `/search`, `/health` and `/ws` to the API (`INKBRIDGE_API_URL`, default `http://127.0.0.1:8000`) because the API sends no CORS headers; the canvas is selected with `?canvas=<id>`.
- Add dependencies only when a ticket needs them: `cd server && uv add <pkg>` or `cd web && npm install <pkg>`.
- CI (`.github/workflows/ci.yml`) runs the same lint, test and build; keep `make lint test` green before pushing.

## Architecture

Three processes, one owner of state:

```
tablet browser (web/, Excalidraw)  <-- HTTP + WebSocket -->  server/ API (FastAPI + SQLite)
                                                                   ^ HTTP only
                                                  MCP server (server/.../mcp, stdio) <-- Claude Desktop / Code
```

- **The API is the single owner** of scenes, regions, recognitions and the agent write queue. The MCP server is a thin HTTP client and must never import `inkbridge.db`; a boundary test enforces it.
- **Scene** = one versioned snapshot of Excalidraw elements per document (optimistic `base_version` on PUT).
- **Region** = a set of element ids + server-computed bbox + hashes + crop PNG. Built: manual regions (`created_by='user'`, `POST /documents/{id}/regions`). **Chunks** are regions with `created_by='auto'` (decision [0004](docs/decisions/0004-chunks-replace-manual-regions.md)). Built: the pure clustering step in `chunker.py` (union-find proximity, bound text joins its container, arrows/lines/drafts/deleted elements excluded, reading order, kind hint; INK-030), run inside every scene save with chunks persisted under stable ids (greedy element-id Jaccard match incl. orphaned chunks, `successor_of` on split/merge, reactivation on undo; INK-031, decision [0011](docs/decisions/0011-chunk-identity.md)); `GET /documents/{id}/regions` lists manual regions, `?chunks=true` lists chunks. Built: arrows (short ones merge their two chunks, long ones add `links` rows rebuilt on every save, the arrow and its label join the chunk of its start; INK-032, decision [0013](docs/decisions/0013-arrow-links.md)). *(Planned)*: manual regions winning over a chunk on the same elements (INK-059).
- **Three hashes, three jobs** (built, decision [0005](docs/decisions/0005-content-hash.md)): `stroke_hash` (exact ink, drives `png_stale`), `content_hash` (shape of the ink, ignores ids and absolute position; keys the recognition cache and search index, and later note provenance), `text_hash` (normalised reading, stored on each recognition; will drive early-cutoff staleness in `check_sync`).
- **Recognition** is a cache keyed by `(region, content_hash, source)` (built); precedence `user > agent > gemini`. A changed content hash means new recognition; unchanged or merely moved ink never triggers a model call. Built: the swappable Gemini recognizer (`inkbridge.recognizer`, decision [0006](docs/decisions/0006-gemini-limits.md)). *(Planned)*: the background worker that calls it (INK-014), and crop sync (only the browser can render crops, so it uploads PNGs for stale chunks when idle).
- **Vault loop** *(planned: INK-033..037)*: the backend never writes the vault. A skill (`skills/inkbridge-export`) calls `read_canvas`, writes a note with one marker-bounded block per chunk (`<!-- ink:ID hash:H -->` ... `<!-- /ink -->`), frontmatter `inkbridge: {canvas, exported, chunks:[{id, hash, reading, section}]}`, a plain-URL deep link (`?canvas=&chunk=`, base from `INKBRIDGE_PUBLIC_URL`) and a folded crop preview. `check_sync` compares content hashes, re-reads changed chunks and flags a section stale only if the reading changed (early cutoff). Re-export rewrites only changed blocks.
- **Ask AI is vendor-neutral** *(planned: INK-046..048; only the `questions` table exists)*: the backend stores questions and history (`questions`, `parent_id` for follow-ups). Pull path: any MCP client calls `list_questions` / `answer_question`. Push path (optional): an `AgentRunner` adapter (Claude Code headless for the demo) started by `INKBRIDGE_RUNNER`. Never depend on one vendor's session resume or channels.
- **Write-back** *(queue built in INK-041: `api/ops.py`, `db/ops.py`, `placement.py`, decision [0009](docs/decisions/0009-agent-ops-queue.md); WebSocket, drafts and MCP write tools planned in INK-042..044)*: an agent tool creates an op in `agent_ops` (pending, delivered, applied, accepted/rejected, failed, expired); the API pushes it over WebSocket; the client renders dashed draft elements tagged `customData {author:"agent", draft:true, op_id}`; Accept/Reject/Accept all resolves them. Drafts are normal scene elements, so autosave persists them, but they are excluded from chunking, recognition and export until accepted. `create_canvas` plus `write_text`/`draw_diagram` without an anchor writes a new canvas from scratch. Sketch to diagram uses a two-pass reading (find nodes and arrow ends, draw numbered markers, then ask for Mermaid).
- **Current state**: server built through scenes, manual regions, MCP read tools, image limits, FTS search, schema v2 with the three hashes (INK-029), the chunker with chunk persistence, stable ids and arrow links (INK-030, INK-031, INK-032) and the Gemini recognizer (INK-013, no worker yet), and the agent ops queue with server-side placement (INK-041; no WebSocket push yet). Web: loads and autosaves the scene per `?canvas=` with conflict merge (INK-007, `web/src/sceneSync.ts`, decision [0008](docs/decisions/0008-autosave-conflict-merge.md)); no chunk overlay, crop sync or drafts yet. Check `git log` and `docs/tickets/README.md` for what has merged since; treat tickets not yet merged as planned, not existing.

## Invariants that are easy to break

These describe the target design. Items marked *(planned)* are not built yet, and some unmarked ones guard paths that do not exist yet (they apply as soon as that path is written); see `docs/tickets/README.md` and `git log` for what has merged. Do not assume code exists for them.

- **User ink is never edited or deleted by an agent path** *(enforced by the op queue, INK-041, `tests/test_ops_api.py`)*. Agent ops only add new elements. Enforce in `server/` (reject payloads referencing existing element ids, and ack ids not issued for the op: they must carry its `id_prefix`); a test must fail if the check is removed. The client is not a trusted enforcement point.
- **Hashes use allow-lists.** `stroke_hash`: `id,type,x,y,width,height,angle,points,pressures,isDeleted`. `content_hash`: `type,width,height,angle,points,pressures,text,fontSize,fontFamily` plus `x,y` as offsets from the bbox origin rounded to 0.001 px; no `id`, deleted elements dropped. Never hash `version`, `versionNonce`, `updated`, `seed`, `customData`, or the cache is invalidated by every render.
- **Drafts are not content** *(built in the chunker, INK-030; planned for the recognizer worker INK-014, export INK-037 and the op queue INK-041)*: elements with `customData.draft` are skipped by the chunker, recognizer and export until accepted.
- **The backend never writes the vault** *(planned: export skill INK-037)* and stores no note text. Notes carry their own provenance (ids, content hashes, reading hashes); text outside marker blocks is never touched on re-export.
- **MCP stdio**: stdout carries protocol frames only; log to stderr. The package directory is named `mcp`, so never run scripts from inside it (it shadows the SDK).
- **Mermaid conversion only runs in the browser** (`@excalidraw/mermaid-to-excalidraw`), so `draw_diagram` completes through a client acknowledgement (bounded wait); flowcharts only *(planned: INK-044)*.
- **Do not generate handwriting strokes.** Agents write text boxes, shapes, arrows and Mermaid diagrams.
- **Pressure is real**: freedraw elements carry `pressures` with `simulatePressure=false`; preserve both through load, save and restore (`restoreElements` before `initialData`).
- **Recognition must never block drawing**: it runs after an idle delay, in the background *(worker planned: INK-014)*.
- **Gemini free tier trains on content.** Send only test and eval pages, never personal notes; real notes are read by Claude. The key lives in `GEMINI_API_KEY` (env, never committed, never logged).
- **No Obsidian plugin, no drawing inside the vault, no cross-canvas links** (decision of 22 Oct): Obsidian instances synced by Syncthing would conflict; the backend is the single owner of canvas state.
- **Dev-only helpers stay dev-only**: the Vite `/__log` endpoint writes `web/dev.log` and must not exist in a production build.
- LAN HTTP is not a secure context; features requiring one need a different approach, not a workaround.
- Config. Built: `INKBRIDGE_DATA_DIR`, `INKBRIDGE_DB`, `INKBRIDGE_API_URL` (MCP client and web dev proxy), `INKBRIDGE_DOCUMENT`, `GEMINI_API_KEY`, `GEMINI_MODEL` (see `.env.example`). Planned: `INKBRIDGE_PUBLIC_URL` (deep links, INK-033), `INKBRIDGE_RUNNER` (optional Ask runner, INK-048).

## Workflow

- One ticket per branch and PR: `feat|fix|chore|docs/INK-xxx-slug`. Never commit to `main` for feature work; `main` is protected from force-push.
- Commit messages: imperative subject, optional `INK-xxx:` prefix. **Never add Co-Authored-By or any attribution line**, in commits or PR bodies.
- Commit identity for this repo is `srikarvuchiha@gmail.com` (repo-local config); do not change it.
- Non-obvious decisions get a numbered note in `docs/decisions/` ([0004](docs/decisions/0004-chunks-replace-manual-regions.md) chunks, [0005](docs/decisions/0005-content-hash.md) content hash, [0006](docs/decisions/0006-gemini-limits.md) Gemini limits, 0007 reserved for the Ask runner (INK-046), [0008](docs/decisions/0008-autosave-conflict-merge.md) autosave conflict merge); tool changes update `docs/mcp-tools.md`; keep this file, `docs/mcp-tools.md` and (once it exists) `docs/vault-note-format.md` in step with the code.
- `docs/tickets/` is untracked on purpose: never `git add -A` or `git add docs`; add paths explicitly.
- Cut order when short on time: networkx stretch, E2/E3, the stroke arm of E1, embedded source previews (keep links), Keep on canvas, Accept/Reject (keep Accept all), manual merge/split, then the Ask panel and runner (keep the pull path). Never cut the canvas-to-note path, the stale check, the README or the demo video.
