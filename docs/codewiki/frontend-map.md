# Frontend map (`web/`)

Single page, no router. URL contract shared with vault notes: `/?canvas=<document id>&chunk=<chunk id>` (`src/route.ts`).

| File | Role |
|---|---|
| `src/main.tsx`, `src/App.tsx` | Mounts Excalidraw; wires load, autosave, overlay, ops socket, crop sync, toolbar |
| `src/sceneSync.ts` | Load/autosave with `base_version`; sends only changed elements after the first load/save (`deltaFor`, decision 0036); on 409 merges the server scene and retries (decision 0008) |
| `src/status.ts` | Tiny external store for the save badge (keeps canvas from re-rendering mid-stroke) |
| `src/chunks.ts`, `src/ChunkOverlay.tsx` | Chunk fetch, deep-link focus, toggleable overlay (decision 0014). Tap a label chip (at least 44x32 px) to select that chunk's ink; selected chunks get an orange border; a visible hint explains Merge/Split |
| `src/overrides.ts` | Merge/Split plan on the selection (INK-059); `toggleChunk` and `chunkMark` for tap selection (decision 0037) |
| `src/cropSync.ts` | Renders and uploads PNG crops for stale chunks when idle and saved (decision 0015) |
| `src/opsSocket.ts` | WebSocket client: receives ops, sends `op.applied`/`op.failed` |
| `src/drawOp.ts`, `src/drafts.ts` | Draw `write_text`/`draw_diagram` ops as dashed drafts (Mermaid via `mermaid-to-excalidraw`) |
| `src/resolve.ts`, `src/DraftBar.tsx` | Accept / Reject / Accept all for drafts (decision 0026). `acceptOp`, `draftOps`, `applyVerdict` are pure/testable; the bar shows counts, per-selection and bulk buttons, and "Retry accept" if a PATCH failed after a save |
| `src/timing.ts`, `src/devLog.ts` | `record()` / `timed()` with a swappable sink; `lib/devLog.ts` (dev only) batches lines to Vite's `/__log` -> `web/dev.log` |
| `web/patches/@excalidraw+excalidraw+0.18.1.patch` | `patch-package` (runs on `postinstall`): freedraw `thinning` 0.6 -> 0.3, `streamline` 0.5 -> 0.2; stored `pressures` untouched (decision 0031) |
| `src/view.ts` | Per-device scroll/zoom memory in `localStorage`; keeps fitting the first agent drafts on a freshly created canvas until the user pans or draws |

Not built: Ask AI side panel (INK-049). The web client ignores `question.update` for now.

Tests: `web/tests/*.test.ts` (chunks, cropSync, drafts, opsSocket, overrides, penFeel, resolve, sceneSync, timing, view) run with Node's built-in runner (`npm test`), no framework.

Pressure rule: freedraw keeps `pressures` and `simulatePressure=false`; run `restoreElements` before `initialData`.
