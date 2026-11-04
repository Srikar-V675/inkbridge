# Frontend map (`web/`)

Single page, no router. URL contract shared with vault notes: `/?canvas=<document id>&chunk=<chunk id>` (`src/route.ts`).

| File | Role |
|---|---|
| `src/main.tsx`, `src/App.tsx` | Mounts Excalidraw; wires load, autosave, overlay, ops socket, crop sync, toolbar |
| `src/sceneSync.ts` | Load/autosave with `base_version`; on 409 merges the server scene and retries (decision 0008) |
| `src/status.ts` | Tiny external store for the save badge (keeps canvas from re-rendering mid-stroke) |
| `src/chunks.ts`, `src/ChunkOverlay.tsx` | Chunk fetch, deep-link focus, toggleable overlay (decision 0014) |
| `src/overrides.ts` | Merge/Split buttons acting on the selection (INK-059) |
| `src/cropSync.ts` | Renders and uploads PNG crops for stale chunks when idle and saved (decision 0015) |
| `src/opsSocket.ts` | WebSocket client: receives ops, sends `op.applied`/`op.failed` |
| `src/drawOp.ts`, `src/drafts.ts` | Draw `write_text`/`draw_diagram` ops as dashed drafts (Mermaid via `mermaid-to-excalidraw`) |
| `src/view.ts` | Per-device scroll/zoom memory in `localStorage`; keeps fitting the first agent drafts on a freshly created canvas until the user pans or draws |

Not built: Accept/Reject buttons (INK-045), Ask AI side panel (INK-049).

Tests: `web/tests/*.test.ts` run with Node's built-in runner (`npm test`), no framework.

Pressure rule: freedraw keeps `pressures` and `simulatePressure=false`; run `restoreElements` before `initialData`.
