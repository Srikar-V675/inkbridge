# 0072 One finger pans, the pen draws (INK-173)

Status: accepted. Tablet check pending (one finger pans, pinch, pen pressure, palm rest, Finger draws toggle, top bar fit).

## What Excalidraw 0.18.1 does (read from `web/node_modules/@excalidraw/excalidraw/dist/dev/`)
- `penMode: true` from `initialData.appState` survives `restoreAppState` (`chunk-4FTI6OG3.js:20795-20815`, supplied value wins). Only `togglePenMode` (`index.js:25744`) and the first pen contact (`:27431-27437`, sets `penMode` and `penDetected`) write it; `penDetected` is forced to `false` on restore.
- With penMode on, `handleCanvasPointerDown` (`index.js:27512`) returns before creating an element when `pointerType === "touch"` and the tool is not selection, text or image. **A finger does not draw with the pen, eraser or shapes** (the ticket premise "a finger can still draw" does not hold for these tools).
- One finger on the pen tool does nothing: one-finger pan only exists for the hand tool, wheel button, space or view mode (`:27677`). Two fingers pan, but `scaleFactor` is forced to 1 for `freedraw` with penMode (`:26967`), so pinch zoom is off. A touch pointerdown while a freedraw element is being drawn cancels that stroke (`:27395-27414`), which is how a palm would ruin a stroke if fingers drew.
- The canvas has `touch-action: none`, so the browser never takes touch gestures. The pen-feel patch (decision 0031) changes only `thinning` and `streamline`; it has no pointer or pressure input code.

Baseline run (unmodified build, synthetic PointerEvents, Playwright): a touch drag on the pen tool added no element and did not move the view; two touch pointers moving apart left zoom at 1; a pen drag with pressures drew one stroke. This confirms the source reading.

## Decision
A window capture-phase pointer router (`web/src/app/touchInput.ts`, pure rules in `touchRouting.ts`, wiring in `TouchLayer.tsx`). For a touch pointer that lands on the Excalidraw interactive canvas and routes to pan or ignore, it calls `stopPropagation()` so Excalidraw never sees that finger, tracks the fingers itself and writes `scrollX/scrollY/zoom` with `api.updateScene({appState, captureUpdate: NEVER})`, one write per animation frame. Pen and mouse events are never stopped, so pen strokes (`pressures`, `simulatePressure: false`) and laptop use are unchanged. It touches no tool state, element, `restoreElements` call or patch.

Rejected: switching to Excalidraw's hand tool for the gesture (needs `setActiveTool` to reach React state before Excalidraw's own pointerdown, must restore the tool on every exit path, flickers the tool rail, and still has no one-finger select-or-pan). Rejected: patching Excalidraw further (the patch is bound to exact chunk hashes).

Routing (pinned by `web/tests/touchRouting.test.ts`):

| pointerType | condition | route |
|---|---|---|
| pen, mouse | any | pass (Excalidraw as before) |
| touch | pen down or within 600 ms of a pen event (palm) | ignore (stopped, nothing happens) |
| touch | Finger draws on | pass |
| touch | another finger already passed to Excalidraw | pass |
| touch | already panning (second finger) | pan (pinch) |
| touch | tool is text | pass |
| touch | selection tool, point on an element | pass |
| touch | selection tool, empty canvas | pan |
| touch | any other tool | pan |

- Palm grace `PEN_GRACE_MS = 600`. Pen hover sends `pointermove`, so a hovering pen keeps palms ignored; a pen pointerdown also ends any finger pan in progress.
- Pinch scales by finger spread about the centre, clamped to `ZOOM_MIN`/`ZOOM_MAX` of `shellLogic`; lifting one finger re-anchors so the view does not jump.
- "Finger draws" (quiet toggle left of Chunks, off by default; localStorage `inkbridge-finger-draws`, `1`/`0`) maps to `penMode = !on` and `penDetected = on` through `updateScene`, applied once Excalidraw has finished loading (and again on change). With it on, the router passes touch through and Excalidraw lets a finger draw, for use without a stylus.

## Browser check (Playwright, throwaway API and Vite, synthetic PointerEvents with `setPointerCapture` stubbed)
Touch drag on the pen tool pans by exactly drag / zoom with no element added; two-finger spread 100 to 260 px took zoom 1 to 2.6 with the scene point under the centre unchanged; a pen drag with pressures 0.3 to 0.8 saved one freedraw with 6 pressures and `simulatePressure: false`; a mouse drag drew and the wheel still panned; a touch within 600 ms of a pen event did nothing and after 1 s panned; with the selection tool a touch on empty canvas panned and a touch on a stroke selected it; the toggle made a touch drag draw, survived a reload and, switched off, made the touch pan again.

## Known limits
- The selection hit test is a bounding box grown by 16 screen pixels, ignoring rotation.
- With the text tool, or the selection tool on an element, the finger goes to Excalidraw, so pinch is Excalidraw's there.
- A stylus that reports `pointerType: "touch"` (some Android browsers) is treated as a finger; the toggle is the escape hatch.
- Palm protection relies on pen hover moves; without them only pen-down and the 600 ms tail protect writing (tune `PEN_GRACE_MS`).
- Each pan or pinch frame calls `updateScene`, re-rendering the React tree per frame; INK-174 may move this to a cheaper path.

Pen feel patch and pressure: untouched. `web/tests/penFeel.test.ts` stays green.
