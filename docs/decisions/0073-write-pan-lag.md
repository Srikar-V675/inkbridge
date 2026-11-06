# 0073 Writing and panning lag: bisect, offenders and fixes (INK-174)

Status: accepted, 2026-11-06. Tablet check pending (see the last section).

The owner reported lag when writing and panning on the tablet that stock Excalidraw does not have. No tablet numbers existed, so this ticket measured first on the laptop and fixed what the numbers named.

## Method
- Headless Chromium 155 (software raster, no GPU), CDP `Emulation.setCPUThrottlingRate` 6x (and 1x for the factor), viewport 1280 x 800. Synthetic input over CDP, paced one event per animation frame: a 200-point pen stroke (`pointerType: "pen"`, `force` 0.3..0.9), 100 wheel steps, one finger dragged for 100 moves. One warm-up run is discarded, then 5 measured runs (3 for the one-layer-off variants). Each stroke is undone after it is measured; stroke runs autosave to a throwaway database.
- What is recorded per run: `requestAnimationFrame` deltas (p50, p95, p99), `longtask` entries, the wall time of every `onChange` subscriber summed per move (the harness wraps `api.onChange` and the `onChange` prop in the perf build only), and the main thread's CDP `Performance.getMetrics` `TaskDuration`/`ScriptDuration`/`LayoutDuration`/`RecalcStyleDuration` divided by the moves ("main ms/move"). **The frame deltas turned out flat** (16.7 ms everywhere: one input event per frame never fills a frame in headless Chromium), so main ms/move is the sensitive number; it includes some CDP driver overhead, so compare rows to each other, not to a frame budget. Run-to-run noise on main ms/move is about 3 ms.
- Variants are applied by a Vite plugin in `web/scripts/perf/vite.perf.config.ts` (flags in the page URL, `?off=dots,overlay`), never by switches in the app. `stock` is Excalidraw with its default UI, no shell and no sync (`web/perf/stock.tsx`), `EXCALIDRAW_THROTTLE_RENDER` on in both. `stock-transparent` is stock with a transparent canvas.
- **Same view for every page.** The first harness run compared the app (which opens fitted to all 633 elements) with stock (100 percent at 0,0, about 14 elements visible) and the app drew 7 to 30 times more elements per frame: not comparable. Every page now starts at 100 percent zoom at 0,0 (`--view origin`, the table below); `--view fit` (all 633 elements on screen, zoom 0.1, the worst case) is a second table.
- The fixture is the 640-element real-scale canvas (decision 0053, 633 live elements); `empty` is a blank canvas. All numbers are production builds (`vite build`), which is what `make serve` serves; the dev build is in its own section.
- Not modelled: GPU raster on the tablet (the dot layer repaint is a raster cost this headless run cannot show), real stylus rate (240 Hz). The ratios between rows are what count.

## Before (production build, 6x throttle, fixture canvas, 100 percent at 0,0)
Columns: frame p50, p95, p99 in ms; long tasks per run; `onChange` ms per move (all subscribers); main-thread ms per move; its script part; difference of main ms/move to `built`.

**stroke**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.8 | 33.3 | 0.6 | 0.00 | 28.2 | 8.4 | -3.3 |
| built | 16.7 | 16.8 | 33.4 | 1.2 | 0.94 | 31.4 | 10.4 | - |
| stock-transparent | 16.7 | 16.8 | 33.3 | 1.0 | 0.00 | 30.7 | 9.1 | -0.7 |
| off:every layer | 16.7 | 16.8 | 16.8 | 1.0 | 0.55 | 28.7 | 9.2 | -2.7 |
| off:dots | 16.7 | 16.8 | 33.3 | 0.3 | 0.88 | 28.9 | 9.5 | -2.6 |
| off:overlay | 16.7 | 16.8 | 33.3 | 1.0 | 0.92 | 29.9 | 10.0 | -1.5 |
| off:drafts | 16.7 | 16.8 | 33.3 | 1.3 | 0.82 | 29.5 | 9.7 | -2.0 |
| off:autosave | 16.7 | 16.8 | 33.3 | 0.7 | 0.65 | 29.7 | 9.7 | -1.7 |
| off:rail | 16.7 | 16.8 | 33.3 | 1.0 | 0.95 | 29.8 | 10.0 | -1.6 |
| off:railstore | 16.7 | 16.8 | 33.3 | 1.3 | 0.93 | 31.0 | 10.2 | -0.4 |
| off:topbar | 16.7 | 16.8 | 33.3 | 0.7 | 0.95 | 30.7 | 10.1 | -0.8 |
| off:crops | 16.7 | 16.8 | 33.4 | 1.3 | 0.98 | 31.4 | 10.4 | +0.0 |
| off:ops | 16.7 | 16.8 | 33.3 | 1.0 | 0.98 | 29.8 | 9.9 | -1.6 |
| off:refresh | 16.7 | 16.8 | 16.8 | 1.3 | 0.89 | 28.8 | 9.6 | -2.6 |
| off:touch | 16.7 | 16.8 | 33.3 | 0.7 | 0.97 | 31.1 | 10.3 | -0.3 |
| off:touchzoom | 16.7 | 16.8 | 33.3 | 1.0 | 0.95 | 29.8 | 9.9 | -1.7 |

**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.8 | 16.8 | 0.0 | 0.00 | 28.8 | 4.6 | -5.7 |
| built | 16.7 | 16.8 | 16.8 | 0.0 | 0.79 | 34.6 | 6.5 | - |
| stock-transparent | 16.7 | 16.8 | 16.8 | 1.6 | 0.00 | 31.4 | 5.0 | -3.2 |
| off:every layer | 16.7 | 16.7 | 16.8 | 0.0 | 0.52 | 29.8 | 5.4 | -4.8 |
| off:dots | 16.7 | 16.8 | 16.8 | 0.0 | 0.79 | 30.9 | 5.8 | -3.7 |
| off:overlay | 16.7 | 16.8 | 16.8 | 0.0 | 0.85 | 32.6 | 6.1 | -2.0 |
| off:drafts | 16.7 | 16.8 | 16.8 | 0.0 | 0.64 | 32.3 | 6.1 | -2.3 |
| off:autosave | 16.7 | 16.7 | 16.8 | 0.0 | 0.55 | 32.9 | 6.1 | -1.7 |
| off:rail | 16.7 | 16.7 | 16.8 | 0.0 | 0.78 | 33.3 | 6.4 | -1.3 |
| off:railstore | 16.7 | 16.7 | 16.8 | 0.0 | 0.84 | 34.9 | 6.8 | +0.3 |
| off:topbar | 16.7 | 16.7 | 16.8 | 0.0 | 0.92 | 34.6 | 6.7 | +0.0 |
| off:crops | 16.7 | 16.7 | 16.8 | 0.0 | 0.82 | 34.5 | 6.6 | -0.1 |
| off:ops | 16.7 | 16.7 | 16.8 | 0.0 | 0.89 | 33.0 | 6.3 | -1.6 |
| off:refresh | 16.7 | 16.7 | 16.8 | 0.0 | 0.76 | 31.5 | 5.8 | -3.1 |
| off:touch | 16.7 | 16.7 | 16.8 | 0.0 | 0.78 | 34.6 | 6.6 | -0.0 |
| off:touchzoom | 16.7 | 16.8 | 16.8 | 0.0 | 0.84 | 31.8 | 6.0 | -2.8 |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.00 | 25.2 | 4.7 | -11.4 |
| built | 16.7 | 16.8 | 16.8 | 0.0 | 0.84 | 36.6 | 12.1 | - |
| stock-transparent | 16.7 | 16.8 | 16.8 | 0.0 | 0.00 | 25.5 | 4.8 | -11.1 |
| off:every layer | 16.7 | 16.7 | 16.8 | 0.0 | 0.47 | 31.0 | 10.1 | -5.6 |
| off:dots | 16.7 | 16.8 | 16.8 | 0.0 | 0.85 | 32.3 | 10.9 | -4.3 |
| off:overlay | 16.7 | 16.8 | 16.8 | 0.0 | 0.85 | 34.1 | 11.1 | -2.4 |
| off:drafts | 16.7 | 16.7 | 16.8 | 0.0 | 0.75 | 34.5 | 11.2 | -2.1 |
| off:autosave | 16.7 | 16.8 | 16.8 | 0.0 | 0.57 | 34.8 | 11.2 | -1.8 |
| off:rail | 16.7 | 16.7 | 16.8 | 0.0 | 0.84 | 33.9 | 11.1 | -2.7 |
| off:railstore | 16.7 | 16.8 | 16.8 | 0.0 | 0.83 | 36.6 | 11.9 | +0.0 |
| off:topbar | 16.7 | 16.7 | 16.8 | 0.0 | 0.89 | 36.4 | 11.9 | -0.1 |
| off:crops | 16.7 | 16.7 | 16.8 | 0.0 | 0.87 | 37.4 | 12.4 | +0.9 |
| off:ops | 16.7 | 16.7 | 16.8 | 0.0 | 0.85 | 34.5 | 11.4 | -2.1 |
| off:refresh | 16.7 | 16.8 | 16.8 | 0.0 | 0.81 | 33.5 | 11.2 | -3.1 |
| off:touch | 16.7 | 16.7 | 16.8 | 0.0 | 0.01 | 5.5 | 1.9 | -31.1 |
| off:touchzoom | 16.7 | 16.8 | 16.8 | 0.0 | 0.73 | 28.4 | 6.1 | -8.2 |

### Empty canvas (production, 6x)

**stroke**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.8 | 16.8 | 0.0 | 0.01 | 27.8 | 8.0 | -2.2 |
| built | 16.7 | 16.8 | 33.3 | 0.0 | 0.43 | 30.1 | 9.3 | - |

**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.01 | 18.0 | 3.0 | -5.4 |
| built | 16.7 | 16.8 | 16.8 | 0.0 | 0.40 | 23.3 | 4.3 | - |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.01 | 19.9 | 3.2 | -7.9 |
| built | 16.7 | 16.8 | 16.8 | 0.0 | 0.44 | 27.8 | 9.0 | - |

### 1x throttle (the 6x factor), fixture

**stroke**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.00 | 5.6 | 1.7 | -4.8 |
| built | 16.7 | 16.7 | 16.8 | 0.0 | 0.33 | 10.3 | 3.6 | - |

**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.00 | 9.4 | 1.5 | -2.2 |
| built | 16.7 | 16.7 | 16.8 | 0.0 | 0.31 | 11.5 | 2.2 | - |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.00 | 8.8 | 1.7 | -3.1 |
| built | 16.7 | 16.8 | 16.8 | 0.0 | 0.30 | 11.9 | 4.3 | - |

### Worst case: everything on screen (zoom 0.1, 633 elements), 6x

**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 33.3 | 49.9 | 3.6 | 0.01 | 37.4 | 11.3 | -6.4 |
| built | 16.7 | 33.3 | 49.9 | 3.6 | 1.34 | 43.8 | 14.1 | - |
| off:touchzoom | 16.7 | 33.3 | 49.9 | 3.4 | 1.38 | 43.8 | 13.9 | -0.1 |
| off:dots+overlay | 16.7 | 33.3 | 33.4 | 2.2 | 1.29 | 37.0 | 12.2 | -6.9 |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs built |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 33.4 | 50.0 | 6.4 | 0.01 | 51.9 | 18.7 | -14.5 |
| built | 16.7 | 33.4 | 66.6 | 6.2 | 1.37 | 66.4 | 29.5 | - |
| off:touchzoom | 16.7 | 33.4 | 50.1 | 10.6 | 1.34 | 59.4 | 22.0 | -7.0 |
| off:dots+overlay | 16.7 | 33.4 | 50.0 | 3.2 | 1.30 | 61.2 | 27.4 | -5.2 |

## Dominant costs
Ranked by how much main ms/move falls when the layer is switched off (6x, fixture, 100 percent view; noise about 3 ms; "vs built" columns above).
1. **The finger pan writes a fresh `zoom` object every frame** (`TouchLayer.setView` passes `zoom: { value }` although one finger never changes zoom). Leaving it out (`off:touchzoom`) takes pan-touch from 36.6 to 28.4 ms (-8.2, 22 percent; -7.0 in the worst-case view) and does nothing for the wheel, which never writes it. It is the largest single item and only the touch path has it. Excalidraw treats a new zoom object as a zoom change and re-renders what depends on it.
2. **The dot layer** (`off:dots`: -3.7 wheel, -4.3 touch, 11 to 12 percent). It is the only thing that costs a style recalculation per pan frame (0.9 ms/move at 6x with it on, 0.00 off). Its repaint of a full-viewport gradient on `background-position` is a raster cost this headless run cannot show; on the tablet GPU it is the part most likely to matter. In the worst-case view, dots plus overlay off removes -6.9 ms of the -6.4 ms wheel gap to stock.
3. **`onChange` subscribers.** All six together cost 0.8 to 0.95 ms per move at 6x on the fixture (1.34 in the worst-case view, 0.4 on an empty canvas): they scale with the scene. `off:autosave` (the 640-string signature) saves 0.3, `off:drafts` (two full element scans) 0.15 to 0.2. The floor with every layer off is 0.5 ms (App.onChange itself).
4. **The chunk overlay following scroll while hidden** (`off:overlay`: -2.0 and -2.4, inside the noise): one React commit per pan frame for nothing.
5. Not offenders: ToolRail, railStore, TopBar status, crop sync, ops socket, chunk refresh (all within noise, no pattern), the transparent canvas over a CSS layer (`stock-transparent` equals `stock`), the touch router's own pointer handling.

For writing: built is 3.3 ms (12 percent) above stock on main ms/move; with every layer off it is within 0.5 ms of stock, and no single layer stands out, so the stroke gap is the sum of the `onChange` subscribers plus the dot layer's style work. Frame p95 is 16.8 ms for every variant (33.3 for stock and built alike in the worst-case view): the layers are not dropping frames on this laptop, they take main-thread time a slower tablet CPU then lacks.

## Fix list
The plan's bar was "p95 falls 10 percent or `onChange` costs 1 ms per move". p95 is flat in this harness, so the first half cannot fire; the bar is applied to main ms/move instead (a drop of 10 percent or more, about 3.5 ms, a little over the noise).
- F1 dot layer to compositor-only motion: clears the bar (12 percent on both pans).
- F5 (not in the plan, found by the table) finger pan writes `zoom` only when it changed: clears the bar (22 percent).
- F3 `SceneSync` compares ids and versions without building strings, and F4 gates on the `DraftBar` scans: `onChange` is at 1.34 ms per move in the worst-case view, over the 1 ms line.
- F2 the hidden overlay stops following scroll: 6 percent, under the bar, applied because it is free and the plan asks for it when `off:overlay` helps pan.
- Not changed: everything under "Not offenders".
