# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Inkbridge is a stroke-based canvas (Excalidraw) that MCP agents read from and write to through addressable "regions". Spec of record: `docs/project-doc.html`. Work is planned as numbered tickets (`INK-xxx`) in `docs/tickets/`, which is local and gitignored; read `docs/tickets/README.md` before starting a task.

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
- **Region** = saved selection: element ids + server-computed bbox + `stroke_hash` + crop PNG. Regions are the unit of agent access; there is no auto-segmentation.
- **Recognition** is a cache keyed by `(region, stroke_hash)`; precedence `user > agent > gemini`. A changed hash means new recognition; unchanged ink never triggers a model call.
- **Write-back**: an agent tool creates an op in `agent_ops`; the API pushes it over WebSocket; the client renders dashed draft elements tagged `customData {author:"agent", draft:true, op_id}`; Accept/Reject resolves them. Drafts are normal scene elements, so autosave persists them.
- Current state: skeleton plus a throwaway Day-1 spike in `web/src/App.tsx`. Treat everything in the ticket README as planned, not existing.

## Invariants that are easy to break

- **User ink is never edited or deleted by an agent path.** Agent ops only add new elements. Enforce in `server/` (reject payloads referencing existing element ids); a test must fail if the check is removed. The client is not a trusted enforcement point.
- **Stroke hash uses an allow-list** of ink-defining fields (`id,type,x,y,width,height,angle,points,pressures,isDeleted`). Never hash `version`, `versionNonce`, `updated`, `seed`, `customData`, or the cache is invalidated by every render.
- **MCP stdio**: stdout carries protocol frames only; log to stderr. The package directory is named `mcp`, so never run scripts from inside it (it shadows the SDK).
- **Mermaid conversion only runs in the browser** (`@excalidraw/mermaid-to-excalidraw`), so `draw_diagram` completes through a client acknowledgement; flowcharts only.
- **Do not generate handwriting strokes.** Agents write text boxes, shapes, arrows and Mermaid diagrams.
- **Pressure is real**: freedraw elements carry `pressures` with `simulatePressure=false`; preserve both through load, save and restore (`restoreElements` before `initialData`).
- **Recognition must never block drawing**: it runs after an idle delay, in the background.
- **Gemini free tier trains on content.** Send only test and eval pages, never personal notes. The key lives in `GEMINI_API_KEY` (env, never committed).
- **Dev-only helpers stay dev-only**: the Vite `/__log` endpoint writes `web/dev.log` and must not exist in a production build.
- LAN HTTP is not a secure context; features requiring one need a different approach, not a workaround.

## Workflow

- One ticket per branch and PR: `feat|fix|chore|docs/INK-xxx-slug`. Never commit to `main` for feature work; `main` is protected from force-push.
- Commit messages: imperative subject, optional `INK-xxx:` prefix. **Never add Co-Authored-By or any attribution line**, in commits or PR bodies.
- Commit identity for this repo is `srikarvuchiha@gmail.com` (repo-local config); do not change it.
- Non-obvious decisions get a numbered note in `docs/decisions/`; tool changes update `docs/mcp-tools.md`.
- `docs/tickets/` is untracked on purpose: never `git add -A` or `git add docs`; add paths explicitly.
- Cut order when short on time: `save_transcription`, `search`, `get_neighbors`, Accept/Reject. Never cut the README or demo video.
