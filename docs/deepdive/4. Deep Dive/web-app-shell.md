# Deep Dive: web app shell (`web/src/app/App.tsx`, `main.tsx`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

`app/App.tsx` (405 lines) wires the framework-free modules to Excalidraw. Dev server config (`vite.config.ts`): proxies `/documents`, `/ops`, `/regions`, `/search`, `/health` and `/ws` (websocket) to `INKBRIDGE_API_URL`; a dev-only `/__log` plugin appends request bodies to `web/dev.log`.

## The shell as of 13 Nov 2026 (Updated 13 Nov 2026)

`App.tsx` is now about 25 KB and sits inside a real app shell (INK-117, INK-162, decisions 0066, 0068). The sections after this one describe the 26 Oct wiring and are still useful for startup order, but several parts moved.

- **Routing and canvases home.** `app/Root.tsx` picks the canvases home (`/`, `home/Home.tsx`) or one canvas (`/?canvas=<id>`); `lib/nav.ts` switches in-app with `pushState` and flushes on leave; Archived is a route (`/?view=archived`); an unknown canvas shows "Canvas not found" (INK-118, INK-172, decisions 0069, 0071). Excalidraw mounts before the scene arrives with `initialData` as a promise, with a transparent layer blocking strokes until the scene is open.
- **Shell slots** (`app/Shell.tsx`): top bar (`TopBar.tsx`: Canvases, title, save status via `StatusSlot`, Chunks toggle, Ask, Size, "Finger draws"), tool rail (`ToolRail.tsx`, `railStore.ts`: pen, highlighter as pen at 35% opacity, eraser, box select, shapes, text, three inks, undo/redo through a synthetic Ctrl+Z), zoom pill (`ZoomControl.tsx`), `PaperDots.tsx` (CSS dots moved by `transform`), `WorkingDot.tsx` (pulsing lime dot from `agent.activity`). Excalidraw's own toolbar and menus are hidden by `app/shell.css`. Z-order: paper 0, canvas 1, rail and zoom 5, properties card 6, overlays 6, top bar 7, Ask panel 8.
- **Tool card** (`app/props/`): one card per rail tool, with the shapes picker and a properties card for the active shape or text tool or the selection; never for pen, highlighter or eraser (decisions 0075, 0098).
- **Touch** (`touchInput.ts`, `touchRouting.ts`, `TouchLayer.tsx`, `fingerDraws.ts`, decision 0072): a window capture-phase router stops only touches on the Excalidraw canvas; one finger pans, two pinch-zoom, only the pen draws; palm rejection holds for `PEN_GRACE_MS` (600 ms) after the pen; "Finger draws" is a per-device toggle, off by default.
- **UI size** (`uiScale.ts`, `uiScaleStore.ts`, `UiSizeControl.tsx`, decision 0083): S/M/L = 0.8/0.9/1.0, default Small on a coarse pointer, scales the shell and not the canvas.
- **Sync** moved to `sync/`: `sceneSync.ts` loads and merges per element, `journal.ts` writes ink to IndexedDB within 50 ms and `sender.ts` uploads it, `liveDelta.ts` applies `scene.delta` from other devices, `startupGate.ts` defers the ops socket and crop sync until first paint. There is no 409 reload any more (decisions 0080, 0087, 0088).
- **Ink layer** (`ink/penSamples.ts`, `ink/FastInk.tsx`, decision 0076): every coalesced pen sample reaches the stroke through the patched freedraw handlers, and the stroke in progress is drawn at once on a fast canvas. It needs a secure context, hence `make serve-https`.
- **Panels and overlays.** The Ask panel (`ask/`) is built, so the "Not built" note below is obsolete; offers (`offers/OfferLayer.tsx`) render only when the server has offers on. Drafts are the section in [web-ops-and-drafts.md](web-ops-and-drafts.md).
- **Design rules** (`DESIGN.md`, enforced by `web/tests/designRules.test.ts`): lime means the agent and only the agent, 44 px touch targets, no hex outside `tokens.css`.

## Components (26 Oct snapshot)

- `Canvas` (`:124-144`): memoised so nothing outside the canvas (save status, route) can re-render Excalidraw mid-stroke. `initialData` is built from restored elements and an optional remembered view.
- `SaveBadge`: reads the status store with `useSyncExternalStore`.
- `Notice`: dismissible banner for deep-link outcomes.
- `ChunkOverlay` (`chunks/ChunkOverlay.tsx`, 242 lines): boxes and Merge/Split buttons.
- `applyJump` (`:31-53`): select the chunk's live strokes and `scrollToContent` (`viewportZoomFactor 0.7`, `maxZoom 1`), or for an orphan set scroll/zoom from `viewForBounds`. `captureUpdate: NEVER` so it never enters undo history.

## Startup order (`useEffect`, `:167-266`)

1. Build `CropSync` and `SceneSync`. `exportPng` uses Excalidraw's `exportToBlob` on only the requested elements (white background, `maxWidthOrHeight: 2048`, padding 10).
2. If `?chunk=` is present, `resolveChunk` runs beside the scene load and never holds the canvas back: the jump is applied on the first change event, or immediately if the scene is already up (`pendingJump`, `sceneReady`).
3. `sync.load()` then `restoreElements(...)` **before** Excalidraw mounts, so freedraw `pressures` and `simulatePressure=false` survive. A link wins over the remembered view. `fitOnOpen` is set only for a canvas that has ink.
4. Page lifecycle: `visibilitychange` hidden and `pagehide` call `flushNow()`; pointer events (capture phase) call `crops.setDrawing`; a `blur` clears the pointer set so a pointerup that never arrives cannot stall crop sync.
5. Cleanup disposes both.

`onReload` (conflict merge) keeps the live objects of local elements (one may be a stroke still being drawn) and `restoreElements` only the ones that came from the server.

## Ops socket (`:281-337`)

Starts once `canvasReady`. `onOp` defines `persist`: it `notify`s the scene, then loops `flushNow()` until `sync.hasSaved(ids)` or gives up after `SAVE_ATTEMPTS = 15` tries spaced `SAVE_RETRY_MS = 2000` (about 30 s) and throws "the drafts could not be saved". `flushNow` does not throw when a save fails, so the check is explicit: an acked op is never replayed, so an unsaved draft lost to a reload would be gone for good. After drawing, the first drafts on a fresh canvas fit the viewport. `onChunksUpdated` requests crop sync. `onOpUpdated` sweeps drafts of ops that ended `failed`, `expired` or `rejected` (`DEAD`) with `rejectOp`. `onOpError` with `invalid_transition` and a dead status sweeps too (the op ended while it was being drawn); other errors are logged.

## `onChange` (`:339-388`)

On every Excalidraw change: `sync.notify` (if it really changed, tell crop sync about activity), `cropRef.start()` (the first change means the canvas holds the loaded scene), mark `sceneReady`, apply a pending jump, fit all ink on first open, and otherwise save the view to `localStorage` after 500 ms.

## Not built (26 Oct; obsolete)

The Ask AI panel (INK-049) was not built then; it is now. Accept/Reject moved to server-side verdicts.

## Potential improvements

Pen feel: `patch-package` changes Excalidraw's freedraw constants to `thinning 0.3`, `streamline 0.2` (`web/patches`, decision 0031; tablet tuning pending). Timing: `lib/timing.ts` records go to the dev-only `lib/devLog.ts` sink. LAN lag (INK-074) is open.
