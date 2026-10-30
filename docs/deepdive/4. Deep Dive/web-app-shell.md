# Deep Dive: web app shell (`web/src/App.tsx`, `main.tsx`)

`App.tsx` (405 lines) wires the framework-free modules to Excalidraw. Dev server config (`vite.config.ts`): proxies `/documents`, `/ops`, `/regions`, `/search`, `/health` and `/ws` (websocket) to `INKBRIDGE_API_URL`; a dev-only `/__log` plugin appends request bodies to `web/dev.log`.

## Components

- `Canvas` (`:124-144`): memoised so nothing outside the canvas (save status, route) can re-render Excalidraw mid-stroke. `initialData` is built from restored elements and an optional remembered view.
- `SaveBadge`: reads the status store with `useSyncExternalStore`.
- `Notice`: dismissible banner for deep-link outcomes.
- `ChunkOverlay` (`ChunkOverlay.tsx`, 242 lines): boxes and Merge/Split buttons.
- `applyJump` (`:31-53`): select the chunk's live strokes and `scrollToContent` (`viewportZoomFactor 0.7`, `maxZoom 1`), or for an orphan set scroll/zoom from `viewForBounds`. `captureUpdate: NEVER` so it never enters undo history.

## Startup order (`useEffect`, `:167-266`)

1. Build `CropSync` and `SceneSync`. `exportPng` uses Excalidraw's `exportToBlob` on only the requested elements (white background, `maxWidthOrHeight: 2048`, padding 10).
2. If `?chunk=` is present, `resolveChunk` runs beside the scene load and never holds the canvas back: the jump is applied on the first change event, or immediately if the scene is already up (`pendingJump`, `sceneReady`).
3. `sync.load()` then `restoreElements(...)` **before** Excalidraw mounts, so freedraw `pressures` and `simulatePressure=false` survive. A link wins over the remembered view. `fitOnOpen` is set only for a canvas that has ink; `fitFirstDrafts` for an empty canvas with no remembered view (one an agent just created).
4. Page lifecycle: `visibilitychange` hidden and `pagehide` call `flushNow()`; pointer events (capture phase) call `crops.setDrawing`; a `blur` clears the pointer set so a pointerup that never arrives cannot stall crop sync.
5. Cleanup disposes both.

`onReload` (conflict merge) keeps the live objects of local elements (one may be a stroke still being drawn) and `restoreElements` only the ones that came from the server.

## Ops socket (`:281-337`)

Starts once `canvasReady`. `onOp` defines `persist`: it `notify`s the scene, then loops `flushNow()` until `sync.hasSaved(ids)` or gives up after `SAVE_ATTEMPTS = 15` tries spaced `SAVE_RETRY_MS = 2000` (about 30 s) and throws "the drafts could not be saved". `flushNow` does not throw when a save fails, so the check is explicit: an acked op is never replayed, so an unsaved draft lost to a reload would be gone for good. After drawing, the first drafts on a fresh canvas fit the viewport. `onChunksUpdated` requests crop sync. `onOpUpdated` sweeps drafts of ops that ended `failed`, `expired` or `rejected` (`DEAD`) with `rejectOp`. `onOpError` with `invalid_transition` and a dead status sweeps too (the op ended while it was being drawn); other errors are logged.

## `onChange` (`:339-388`)

On every Excalidraw change: `sync.notify` (if it really changed, tell crop sync about activity), `cropRef.start()` (the first change means the canvas holds the loaded scene), cancel `fitFirstDrafts` when the user pans, zooms or draws (`keepFittingFirstDrafts`), mark `sceneReady`, apply a pending jump, fit all ink on first open, and otherwise save the view to `localStorage` after 500 ms.

## Not built

Accept/Reject buttons and the Ask AI panel (INK-045, INK-049). `rejectOp` is wired only for ops that die elsewhere.

## Potential improvements

INK-062 (pen pressure and lag) cannot be fixed in this layer; Excalidraw hardcodes `thinning 0.6`, `smoothing 0.5`, `streamline 0.5`.
