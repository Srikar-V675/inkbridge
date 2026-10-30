# Deep Dive: web crop sync (`web/src/cropSync.ts`)

Only the browser can render Excalidraw, so crops of stale chunks are rendered and uploaded here (INK-057, decision 0015). The server flags a chunk `png_stale` when its ink changes; this class finds those chunks and uploads PNGs.

## Rules (file header, `:1-5`)

- Never while drawing: pointer down, or any change in the last `idleMs` (default 2000 ms).
- Only when the canvas equals a **saved** scene version (`settledVersion()` is not null).
- The upload carries that version, so the server can refuse a crop of older ink (`PUT /regions/{id}/image`, 409).

## Wiring

`CropSyncOptions`: `documentId`, `exportPng(elementIds) -> Blob | null` (App supplies Excalidraw's export), `settledVersion()` (from `SceneSync`), optional `fetchFn`, `idleMs`, `now`, `yieldFn` (default `setTimeout(0)`, lets the browser handle input between exports; each export blocks the main thread).

## Lifecycle

- `start(pollMs = 30_000)`: once the canvas shows the loaded scene; marks activity, then `poll()` every 30 s calling `request()`. Nothing runs before `start`.
- `request()`: sets `wanted` and schedules a run after the remaining idle time. Called on load, after a save, and on the WebSocket's `chunks.updated`.
- `activity()`: a scene change or pointer event restarts the idle clock. `setDrawing(down)`: nothing is exported while the pointer is down.
- `dispose()`: stops timers.

## `run()` (`:115-162`)

1. Return if disposed, already running, or nothing wanted. Wait for idle (`idleLeft`).
2. `version = settledVersion()`. If `null` (unsaved edits or save in flight) reschedule after `idleMs` without a request, so a "saved" state emitted mid-save is not lost until the next poll.
3. If `version === refusedAt` return: a 409 earlier at this version means this tab is behind the stored scene; polling again would just export and be refused again. Cleared by the next save or reload (a different version).
4. Fetch stale chunks: `GET /documents/{id}/regions?chunks=true&png_stale=true&status=active&limit=500`, filter to `png_stale && status === "active"`. (A TODO in the file notes INK-033 added `GET /documents/{id}/chunks?png_stale=1`; this still uses the regions list.)
5. For each chunk: `yieldFn()`, then check `busy(since, version)` (disposed, drawing, activity since the start, or version changed) and stop if so (re-arming `wanted`); `exportPng(element_ids)`; **check busy again** because an edit during the export may be in the picture but not in the saved scene; skip when `png` is null; upload `FormData{image, scene_version}`; `409` sets `refusedAt` and stops.
6. A chunk that cannot be rendered (exception) is skipped so it cannot starve the ones after it. Network failure leaves crops stale; the next request or poll catches up.

## Why this matters

Crops feed `get_region`, `read_canvas`'s overview, vault embeds and the recognition worker (which only reads chunks with a fresh crop, `png_stale = 0`). A crop of older ink marked fresh would make the worker read the wrong ink, hence the version handshake enforced by compare-and-set on the server (`db.mark_png_fresh`).

## Testing

`web/tests/cropSync.test.ts` (9.3K) and server `tests/test_crop_sync.py`.
