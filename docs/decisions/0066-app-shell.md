# 0066: App shell

Status: accepted (INK-117). Owner checks pending: visual match on the tablet and laptop, pen feel, dots while panning and pinch-zooming (`?devicelog=1` / `?probe=1`).

## Context

The Main board puts the canvas on dotted paper with a top bar, a tool rail and a zoom control, and none of Excalidraw's own chrome. Excalidraw 0.18.1 gives us a see-through canvas and an imperative API, but it cannot hide its toolbar from props, has no lasso tool and no undo or redo method.

## Decision

- **Paper dots are a CSS layer under a transparent canvas** (`PaperDots`, `shellLogic.paperDots`). `initialAppState` sets `viewBackgroundColor: "transparent"`; `shell.css` makes `.excalidraw` and its canvas container transparent. The tile is 24 scene units (doubled until a gap is at least 10 px), a dot sits at the centre of each tile, and `api.onScrollChange` writes three CSS variables (`--ink-dot-size`, `-x`, `-y`) straight onto the element: no React state, no re-render while panning. Crop export is unaffected (`exportToBlob` passes its own `viewBackgroundColor`).
- **Measured cost of the dots.** Headless Chromium (software raster, 1280x800, 60 Hz), a 2000-line-per-frame canvas 2D load standing in for Excalidraw, with and without rewriting `background-size` and `background-position` of a full-viewport `radial-gradient` every animation frame for 240 frames, twice each: average frame 16.67 to 17.01 ms in both arms, p95 16.8 ms in both. No measurable cost. The tablet check (INK-102) stays an owner check.
- **Excalidraw's chrome is hidden by CSS**, not by `UIOptions`: `UIOptions` only has `canvasActions` and `tools.image`. `App` passes `UIOptions` with every canvas action off and images off (a module-level constant, so the memo never re-renders the canvas), and `shell.css` hides `.layer-ui__wrapper` and `.context-menu`. Keyboard shortcuts keep working; only the DOM chrome goes.
- **Lasso is the selection tool.** There is no `lasso` tool in 0.18.1, so the rail's "Lasso select" button activates box selection until a real lasso exists. Merge/split still say "lasso" in their hint text.
- **Highlighter is freedraw at 35 percent opacity, width 4, in the chosen ink colour.** No new colour (lime is the agent). Pen restores 100 percent and width 2; shapes and text also reset opacity and width so they do not inherit the highlighter. The rail only patches `currentItemOpacity` and `currentItemStrokeWidth` (a test forbids any other key, so pressure state is never touched), and every change goes through `updateScene` with `CaptureUpdateAction.NEVER`, so none of it is an undo step.
- **Undo and redo are a synthetic Ctrl/Cmd+Z (Shift for redo) keydown** on the `.excalidraw` container, because the API has no undo method. Checked in a browser: a drawn stroke is undone and redone.
- **The rail store** (`railStore.ts`) returns the same snapshot object until the tool, pen colour or zoom changes, so `useSyncExternalStore` does not re-render during a stroke. It starts the pen in charcoal once Excalidraw has finished loading (`appState.isLoading`; its async `initialData` would overwrite an earlier choice), and does not switch tool when a deep link already selected a chunk, because choosing the pen clears the selection. It is built in an effect, since calling the API during render is a React error. `CaptureUpdateAction`, key events and `requestAnimationFrame` are injected so the Node tests need not load Excalidraw.
- **Slot contract for later tickets.** `Shell({api, title, status, chunks?, onAsk, askOpen, children})`: INK-162 fills `status` and `chunks`, INK-161 owns the panel `onAsk` opens, INK-118 owns the title list. `StatusSlot` is a placeholder body (check plus "Saved" or the old words) that INK-162 rewrites.
- **`AskPanel({api, canvas, open, onClose})`**: `App` owns `askOpen`; the panel returns null when closed and the floating "Ask AI" opener is gone. INK-161 rebuilds the panel behind the same props.
- The title comes from `GET /documents` (`canvasTitle.ts`), falling back to the canvas id; it never throws.
- `ChunkOverlay`'s two `bottom` offsets moved up 16 px to clear the zoom control. Interim: INK-162 moves the toggle into the top bar.

## Consequences

- `App.tsx` stays in the `LEGACY` hex list (crop export white, `Notice` yellow).
- The z-order is paper (0), canvas and overlays (1), top bar, rail and zoom (5), Ask panel and draft bar (10).
- Real lasso, a toolbar-free Excalidraw build and an undo API would each remove a workaround here.
