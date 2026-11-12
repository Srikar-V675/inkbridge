# Inkbridge deep-dive documentation

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

Code-level documentation generated with the `smart-docs` skill (C4 diagrams, workflows, one page per major module, with `file:line` references). The product-level wiki is [`../codewiki/`](../codewiki/overview.md).

1. [Project Overview](1.%20Project%20Overview.md)
2. [Architecture Overview](2.%20Architecture%20Overview.md)
3. [Workflow Overview](3.%20Workflow%20Overview.md)
4. Deep Dive
   - Server: [chunker](4.%20Deep%20Dive/chunker.md) · [database](4.%20Deep%20Dive/database.md) · [recognition](4.%20Deep%20Dive/recognition.md) · [check-sync](4.%20Deep%20Dive/check-sync.md) · [ops-queue-and-websocket](4.%20Deep%20Dive/ops-queue-and-websocket.md) · [api-routes-and-limits](4.%20Deep%20Dive/api-routes-and-limits.md) · [sketch-to-diagram](4.%20Deep%20Dive/sketch-to-diagram.md) · [mcp-server](4.%20Deep%20Dive/mcp-server.md) · [questions-api](4.%20Deep%20Dive/questions-api.md) · [scene-delta-saves](4.%20Deep%20Dive/scene-delta-saves.md)
   - Skill: [export-skill-and-vault-note](4.%20Deep%20Dive/export-skill-and-vault-note.md)
   - Web: [web-app-shell](4.%20Deep%20Dive/web-app-shell.md) · [web-scene-sync](4.%20Deep%20Dive/web-scene-sync.md) · [web-crop-sync](4.%20Deep%20Dive/web-crop-sync.md) · [web-chunks-overlay-overrides](4.%20Deep%20Dive/web-chunks-overlay-overrides.md) · [web-ops-and-drafts](4.%20Deep%20Dive/web-ops-and-drafts.md)

Line numbers are approximate and refer to `main` on 26 Oct 2026, except where a section says Updated 13 Nov 2026 (feature freeze); the packages were split since (`db/`, `canvas/chunker/`, `mcp/tools/`), so prefer module and function names. Pages refreshed on 13 Nov: chunker, recognition, export-skill-and-vault-note, web-app-shell, web-ops-and-drafts, ops-queue-and-websocket, database, mcp-server; the rest carry a short update note. No pages were added.
