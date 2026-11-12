# Inkbridge: overview

**One-liner:** a handwritten Excalidraw canvas wired into a markdown vault. The server groups ink into addressable **chunks**; MCP agents (Claude Desktop / Claude Code) read the whole canvas, write vault notes that trace back to the ink, answer questions, and draw back as **drafts** the user accepts or rejects.

**Users:** one note-taker who writes on a tablet browser and keeps notes in an Obsidian-style markdown vault, using Claude as the agent.

**Status:** feature freeze, 13 Nov 2026. Build deadline was 27 Oct, submission 28 Oct; the v4 wave (Nov) is merged. Not part of the freeze: the demo video and the real-page evals. See [roadmap.md](roadmap.md).

**Specs of record**
- Spec v3 (final, 23 Oct 2026): https://claude.ai/artifact/FkyFV1UySxqfC9oFEYb1P1
- Technical reference v3: https://claude.ai/artifact/1uMmVHEyuvb2uS5Dgutaqy (a local, untracked copy may exist at `docs/tech/technical-reference.html`)
- `docs/project-doc.html` is the v1 draft, history only.
- Tickets (`INK-xxx`) live in `docs/tickets/` (local, gitignored). Decisions: `docs/decisions/`.

## Components

| Part | Path | Stack | Role |
|---|---|---|---|
| Web client | `web/` | React 19, Vite 8, `@excalidraw/excalidraw` 0.18, `@excalidraw/mermaid-to-excalidraw` | App shell (top bar, tool rail, props card), canvases home, device journal and live delta, chunk overlay, Ask panel, drafts, crop upload |
| API | `server/src/inkbridge/api/` | FastAPI, SQLite (raw `sqlite3`), Pillow, networkx | Single owner of per-element scenes, chunks, recognitions, ops and drafts, questions, tasks, diagrams |
| MCP server | `server/src/inkbridge/mcp/` | MCP Python SDK 2.x, stdio | Thin HTTP client of the API, never imports `inkbridge.db` |
| Recognizer + worker | `recognizer/` (`gemini.py`, `claude.py`, `worker.py`) | `google-genai` (Gemini, test pages) or one persistent `claude -p` Haiku session | Background handwriting reading, opt-in per canvas, chosen by `INKBRIDGE_RECOGNIZER` |
| Export skill | `skills/inkbridge-export/` | Claude skill + stdlib helper | Writes vault notes; the backend never writes the vault |

Architecture type: **modular monolith** (one API process) plus a browser client and a stdio MCP adapter.

## What is built (feature freeze, 13 Nov 2026)

- **Canvas and sync:** per-element scene storage (`scene_elements` rows, per-element merge, no 409), an IndexedDB device journal and sender, live `scene.delta` over WebSocket to other devices, canvases home, app shell, pen/finger touch routing, fast ink layer, UI size S/M/L.
- **Chunks:** chunker v2 is the default (stroke kinds, lines, connectors), oversized chunks are cut at their widest gaps (`canvas/chunker/split.py`), stable ids, manual merge/split, link-based graph view (`get_subgraph`, `canvas_components`).
- **Reading:** Gemini (test pages) or Claude Haiku (`recognizer/claude.py`, one persistent session) in a background worker; the reader gets a diagram structure hint (`canvas/structure.py`).
- **Vault loop:** `read_canvas`, `retrieve`, `check_sync` with early cutoff, the `inkbridge-export` skill with a learning loop.
- **Agents:** Ask panel with streaming answers, agent tasks (`list_tasks` / `claim_task` / `complete_task`) and the optional `claude` runner, every agent told it is inside a canvas (`canvas_context.py`), drafts that live in the `agent_ops` row until Accept, diagram objects with `edit_diagram` and mark-up as instruction, a per-canvas brief and `what_changed`.
- **Proactive offers:** built (table, detectors, latest-ink read, chips) but **OFF by default** (`INKBRIDGE_OFFERS=1` turns them on, decision 0121).
- Offline eval harness (`eval/`) on synthetic data only.

Not built or not verified: see "Not built / future" and "Known limits" in [roadmap.md](roadmap.md).

## Read next
[architecture.md](architecture.md) · [user-flows/index.md](user-flows/index.md) · [api-reference.md](api-reference.md) · [data-models.md](data-models.md) · [frontend-map.md](frontend-map.md) · [commands.md](commands.md) · [env-vars.md](env-vars.md) · [glossary.md](glossary.md) · [roadmap.md](roadmap.md)
