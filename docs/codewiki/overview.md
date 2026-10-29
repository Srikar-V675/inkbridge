# Inkbridge: overview

**One-liner:** a handwritten Excalidraw canvas wired into a markdown vault. The server groups ink into addressable **chunks**; MCP agents (Claude Desktop / Claude Code) read the whole canvas, write vault notes that trace back to the ink, answer questions, and draw back as **drafts** the user accepts or rejects.

**Users:** one note-taker who writes on a tablet browser and keeps notes in an Obsidian-style markdown vault, using Claude as the agent.

**Deadline:** build by 27 Oct 2026, submit 28 Oct 2026.

**Specs of record**
- Spec v3 (final, 23 Oct 2026): https://claude.ai/artifact/FkyFV1UySxqfC9oFEYb1P1
- Technical reference v3: https://claude.ai/artifact/1uMmVHEyuvb2uS5Dgutaqy (an earlier local copy is `docs/tech/technical-reference.html`)
- `docs/project-doc.html` is the v1 draft, history only.
- Tickets (`INK-xxx`) live in `docs/tickets/` (local, gitignored). Decisions: `docs/decisions/`.

## Components

| Part | Path | Stack | Role |
|---|---|---|---|
| Web client | `web/` | React 19, Vite 8, `@excalidraw/excalidraw` 0.18, `@excalidraw/mermaid-to-excalidraw` | Canvas, autosave, chunk overlay, draft rendering, crop upload |
| API | `server/src/inkbridge/api/` | FastAPI, SQLite (raw `sqlite3`), Pillow | Single owner of scenes, chunks, recognitions, ops queue |
| MCP server | `server/src/inkbridge/mcp/` | MCP Python SDK 2.x, stdio | Thin HTTP client of the API, never imports `inkbridge.db` |
| Recognizer + worker | `recognizer/`, `recognition_worker.py` | `google-genai` (Gemini) | Background handwriting reading, opt-in per canvas |
| Export skill | `skills/inkbridge-export/` | Claude skill + stdlib helper | Writes vault notes; the backend never writes the vault |

Architecture type: **modular monolith** (one API process) plus a browser client and a stdio MCP adapter.

## What is built vs planned (as of branch `review/all-latest`)

Built: scenes with optimistic versioning, manual regions, chunker with stable ids and arrow links, manual merge/split, chunks API, `read_canvas` / `search` / `check_sync` / `write_text` / `create_canvas` / `draw_diagram` / sketch-to-diagram, Gemini recognizer and worker, ops queue with WebSocket push and draft rendering, deep links and overlay, crop sync, vault export skill.

Planned: Accept/Reject UI (INK-045), Ask AI (INK-046..049), eval (INK-050..053, 061), README and demo (INK-054/055), pen-feel fix (INK-062). See [roadmap.md](roadmap.md).

## Read next
[architecture.md](architecture.md) · [user-flows/index.md](user-flows/index.md) · [api-reference.md](api-reference.md) · [data-models.md](data-models.md) · [frontend-map.md](frontend-map.md) · [commands.md](commands.md) · [env-vars.md](env-vars.md) · [glossary.md](glossary.md) · [roadmap.md](roadmap.md)
