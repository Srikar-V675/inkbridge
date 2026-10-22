# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Inkbridge is a handwritten canvas (Excalidraw) wired into a markdown vault: the server groups ink into addressable **chunks**, MCP agents read the whole canvas, write vault notes that trace back to the ink, answer questions, and draw back as drafts the user accepts or rejects.

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
- Web has no test runner yet; checks are `npm run lint`, `npx tsc -b`, `npm run build` (run in `web/`).
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
- **Region** = a set of element ids + server-computed bbox + hashes + crop PNG. **Chunks** are regions with `created_by='auto'`, proposed by the server after every scene save (`chunker.py`: union-find proximity, arrows add links or merge, bound text joins its container); manual regions (`created_by='user'`) still work and win over a chunk on the same elements. Chunk ids stay stable across edits (element-id Jaccard match); a split or merge orphans the old chunk and sets `successor_of`.
- **Three hashes, three jobs** (decision 0005): `stroke_hash` (exact ink, drives the crop and `png_stale`), `content_hash` (shape of the ink, ignores ids and position; drives the recognition cache and note provenance), `text_hash` (normalised reading; drives early-cutoff staleness).
- **Recognition** is a cache keyed by `(region, content_hash, source)`; precedence `user > agent > gemini`. A changed content hash means new recognition; unchanged or merely moved ink never triggers a model call. Only the browser can render crops, so it uploads PNGs for stale chunks when idle (crop sync).
- **Vault loop**: the backend never writes the vault. A skill (`skills/inkbridge-export`) calls `read_canvas`, writes a note with one marker-bounded block per chunk (`<!-- ink:ID hash:H -->` ... `<!-- /ink -->`), frontmatter `inkbridge: {canvas, exported, chunks:[{id, hash, reading, section}]}`, a plain-URL deep link (`?canvas=&chunk=`, base from `INKBRIDGE_PUBLIC_URL`) and a folded crop preview. `check_sync` compares content hashes, re-reads changed chunks and flags a section stale only if the reading changed (early cutoff). Re-export rewrites only changed blocks.
- **Ask AI is vendor-neutral**: the backend stores questions and history (`questions`, `parent_id` for follow-ups). Pull path: any MCP client calls `list_questions` / `answer_question`. Push path (optional): an `AgentRunner` adapter (Claude Code headless for the demo) started by `INKBRIDGE_RUNNER`. Never depend on one vendor's session resume or channels.
- **Write-back**: an agent tool creates an op in `agent_ops` (pending, delivered, applied, accepted/rejected, failed, expired); the API pushes it over WebSocket; the client renders dashed draft elements tagged `customData {author:"agent", draft:true, op_id}`; Accept/Reject/Accept all resolves them. Drafts are normal scene elements, so autosave persists them, but they are excluded from chunking, recognition and export until accepted. `create_canvas` plus `write_text`/`draw_diagram` without an anchor writes a new canvas from scratch. Sketch to diagram uses a two-pass reading (find nodes and arrow ends, draw numbered markers, then ask for Mermaid).
- **Current state**: the server is built through scenes, regions, MCP read tools, image limits and FTS search; the rest of the v3 design is ticketed (check `git log` and `docs/tickets/README.md` for what has merged). The web client may still be the Day-1 spike in `web/src/App.tsx`. Treat tickets not yet merged as planned, not existing.

## Invariants that are easy to break

These describe the target design. Items marked *(planned)* are not built yet (see `docs/tickets/README.md` and `git log` for what has merged); do not assume code exists for them.

- **User ink is never edited or deleted by an agent path.** Agent ops only add new elements. Enforce in `server/` (reject payloads referencing existing element ids, and ack ids that already exist); a test must fail if the check is removed. The client is not a trusted enforcement point.
- **Hashes use allow-lists.** `stroke_hash`: `id,type,x,y,width,height,angle,points,pressures,isDeleted`. `content_hash`: the same minus `id`, positions as offsets from the bbox origin, deleted elements dropped. Never hash `version`, `versionNonce`, `updated`, `seed`, `customData`, or the cache is invalidated by every render.
- **Drafts are not content** *(planned: chunker INK-030, op queue INK-041)*: elements with `customData.draft` are skipped by the chunker, recognizer and export until accepted.
- **The backend never writes the vault** *(planned: export skill INK-037)* and stores no note text. Notes carry their own provenance (ids, content hashes, reading hashes); text outside marker blocks is never touched on re-export.
- **MCP stdio**: stdout carries protocol frames only; log to stderr. The package directory is named `mcp`, so never run scripts from inside it (it shadows the SDK).
- **Mermaid conversion only runs in the browser** (`@excalidraw/mermaid-to-excalidraw`), so `draw_diagram` completes through a client acknowledgement (bounded wait); flowcharts only.
- **Do not generate handwriting strokes.** Agents write text boxes, shapes, arrows and Mermaid diagrams.
- **Pressure is real**: freedraw elements carry `pressures` with `simulatePressure=false`; preserve both through load, save and restore (`restoreElements` before `initialData`).
- **Recognition must never block drawing**: it runs after an idle delay, in the background.
- **Gemini free tier trains on content.** Send only test and eval pages, never personal notes; real notes are read by Claude. The key lives in `GEMINI_API_KEY` (env, never committed, never logged).
- **No Obsidian plugin, no drawing inside the vault, no cross-canvas links** (decision of 22 Oct): Obsidian instances synced by Syncthing would conflict; the backend is the single owner of canvas state.
- **Dev-only helpers stay dev-only**: the Vite `/__log` endpoint writes `web/dev.log` and must not exist in a production build.
- LAN HTTP is not a secure context; features requiring one need a different approach, not a workaround.
- Config. Built: `INKBRIDGE_DATA_DIR`, `INKBRIDGE_DB`, `INKBRIDGE_API_URL`, `INKBRIDGE_DOCUMENT`; web dev proxy target `INKBRIDGE_API_URL`. In open PRs: `GEMINI_API_KEY`, `GEMINI_MODEL` (INK-013). Planned: `INKBRIDGE_PUBLIC_URL` (deep links, INK-033), `INKBRIDGE_RUNNER` (optional Ask runner, INK-048).

## Workflow

- One ticket per branch and PR: `feat|fix|chore|docs/INK-xxx-slug`. Never commit to `main` for feature work; `main` is protected from force-push.
- Commit messages: imperative subject, optional `INK-xxx:` prefix. **Never add Co-Authored-By or any attribution line**, in commits or PR bodies.
- Commit identity for this repo is `srikarvuchiha@gmail.com` (repo-local config); do not change it.
- Non-obvious decisions get a numbered note in `docs/decisions/` (0004 chunks replace manual regions; 0005 content hash and 0006 Gemini limits arrive with INK-029 and INK-013); tool changes update `docs/mcp-tools.md`; keep this file, `docs/mcp-tools.md` and (once it exists) `docs/vault-note-format.md` in step with the code.
- `docs/tickets/` is untracked on purpose: never `git add -A` or `git add docs`; add paths explicitly.
- Cut order when short on time: networkx stretch, E2/E3, the stroke arm of E1, embedded source previews (keep links), Keep on canvas, Accept/Reject (keep Accept all), manual merge/split, then the Ask panel and runner (keep the pull path). Never cut the canvas-to-note path, the stale check, the README or the demo video.
