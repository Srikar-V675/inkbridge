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

## After
Same production build and method, fixture canvas, 100 percent at 0,0, 6x. The machine was busier than during the first run (stock itself moved from 28 to 42 ms main/move), so the comparison that counts was run **back to back in one session, twice, interleaved**: the build before the fixes (commit 5700106, the old `src/`, plus the harness) and the build after, each against its own stock page; the two runs are pooled. "built / stock main" is the within-session ratio, the number to read.

| scenario | variant | session | p50 | p95 | p99 | long/run | onChange ms/move | main ms/move | script | built / stock main |
|---|---|---|---|---|---|---|---|---|---|---|
| stroke | stock | before | 16.7 | 33.4 | 50.0 | 6.4 | 0.01 | 41.9 | 13.5 | - |
| stroke | built | before (04256d2 + harness) | 16.7 | 33.4 | 50.0 | 6.0 | 1.50 | 44.0 | 15.8 | 1.05 |
| stroke | stock | after | 16.7 | 33.4 | 50.0 | 5.1 | 0.01 | 42.1 | 13.6 | - |
| stroke | built | after | 16.7 | 33.4 | 50.0 | 6.4 | 1.10 | 43.1 | 15.4 | 1.02 |
| pan-wheel | stock | before | 16.7 | 33.4 | 33.4 | 2.7 | 0.01 | 44.1 | 7.3 | - |
| pan-wheel | built | before (04256d2 + harness) | 16.7 | 33.4 | 50.0 | 3.7 | 1.38 | 51.9 | 10.2 | 1.18 |
| pan-wheel | stock | after | 16.7 | 33.4 | 50.0 | 5.1 | 0.01 | 45.3 | 7.5 | - |
| pan-wheel | built | after | 16.7 | 33.4 | 33.5 | 2.8 | 0.80 | 47.6 | 8.3 | 1.05 |
| pan-touch | stock | before | 16.7 | 16.8 | 33.4 | 0.9 | 0.01 | 38.8 | 7.7 | - |
| pan-touch | built | before (04256d2 + harness) | 16.7 | 33.4 | 50.0 | 1.5 | 1.39 | 53.8 | 18.8 | 1.39 |
| pan-touch | stock | after | 16.7 | 16.8 | 33.4 | 1.3 | 0.01 | 39.0 | 7.8 | - |
| pan-touch | built | after | 16.7 | 33.3 | 33.4 | 0.7 | 0.76 | 42.4 | 8.3 | 1.09 |

What moved: the touch pan fell from 1.39x stock to 1.09x (main 53.8 to 42.4 ms/move, script 18.8 to 8.3), the wheel pan from 1.18x to 1.05x, the stroke from 1.05x to 1.02x; `onChange` per move fell from 1.4-1.5 to 0.8-1.1 ms. Frame p50/p95/p99 are the same (or within one 16.7 ms step, noise on a loaded machine) before and after: on this laptop frames were never dropped, the saved time is main-thread time a tablet CPU does not have to spare. The ticket's acceptance bar (within 20 percent of stock on p95 frame time) is **not demonstrated**: see "What this does and does not show" below.

Worst case (all 633 elements on screen, zoom 0.1), one session after the fixes: wheel built 42.3 vs stock 36.0 main ms/move (+6.3, was +6.4 before), touch 58.4 vs 54.2 (+4.3, was +14.5), stroke 40.9 vs 41.9. The wheel gap there is the dot layer's style work and the remaining `onChange` subscribers; it did not move.

Guard (`npm run perf -- --guard`, quiet machine, 6x, 100 percent view): built within 20 percent + 2 ms of stock on p95 and `onChange` under 2 ms/move for stroke and finger pan on the fixture and the empty canvas: all four cases ok on that one hand-run on a quiet machine (see below: it can fail on a busy one). Quiet-machine `onChange` per move: 0.69 (fixture stroke), 0.45 (fixture pan), 0.35 (empty stroke), 0.23 (empty pan) ms; finger pan main ms/move built 24.6 vs stock 23.9 on the fixture, 19.1 vs 15.3 on the empty canvas.

## What this does and does not show
- **Frame p95 is quantised and unresolved here.** `requestAnimationFrame` deltas come in 16.7 ms steps, so p95 reads 16.8 or 33.3 and a single slow frame flips it. On the loaded machine of the A/B session stock itself sat at 33.4 ms p95 in two scenarios, and in the pan-touch A/B row built read p95 33.3 against stock 16.8, a failure of the plan's "within 20 percent at p95" test taken literally. **That criterion is therefore not demonstrated by this ticket.** The same p95 was 16.8 for both on the quiet-machine runs, but that is one run, not proof.
- **What is demonstrated** is main-thread time per move at 6x throttle, compared with stock within one session: built / stock for the finger pan 1.39 to 1.09, wheel 1.18 to 1.05, stroke 1.05 to 1.02, and `onChange` per move 1.4-1.5 to 0.8-1.1 ms. Read these with the roughly 3 ms run-to-run noise of that number; the finger pan (about 11 ms) is well outside it, the wheel and stroke improvements are small and partly inside it. It includes some CDP driver overhead, so it is a ratio, not a frame budget.
- **The guard** (`npm run perf -- --guard`) passed on one hand-run on a quiet machine. It is not run by `checks.sh` or CI (it needs a built bundle, a seeded server and Chromium), and on a busy machine the p95 test can fail on quantisation alone. It now also fails, rather than passes silently, on a missing number or a scenario in which the driver did nothing (`perfHarness.test.ts`). What CI does guard: the patches' drift test, the `notify` cost test in `sceneSync.test.ts`, and the paper layer rules.
- **The owner's tablet lag was not reproduced in headless frame times.** Neither stock nor our app dropped frames on this laptop at 6x with one input event per frame, so the table says where main-thread time goes and what was removed, not that the tablet now feels like excalidraw.com. GPU raster of the dot layer and a real stylus rate are not modelled. **The real verdict is the tablet run** (last section).

## Fixes
- **F1 dot layer, applied** (cause 2, 12 percent on both pans). `PaperDots` moves a layer one tile larger than the view by `translate3d` only, snapped to whole device pixels so the compositor does not resample the dots; the tile-size variable is written only when the zoom changes; one write per frame, queued with a `requestAnimationFrame` so it lands in the frame Excalidraw's throttled redraw uses (the old synchronous write could lead the ink by a frame). `background-position` and `--ink-dot-x/y` are gone (`shell.test.ts` fails if they return). Look unchanged by this ticket (the tile and dot are whatever `shellLogic.ts` and `shell.css` say: after INK-170 a 36 px tile and a 1 px dot in `--color-paper-dot`; the layer is expressed in the tile-size variable, so a new tile needs no CSS change); screenshots before and after (taken with the 24 px tile of the time) at five scroll and zoom values differ by at most 1 of 765 colour levels at 100 percent and by sub-pixel anti-aliasing where the offset is fractional. `DESIGN.md` needs no change.
- **F5 finger pan writes `zoom` only when it changed, applied** (cause 1, 22 percent; not in the plan, found by the table). `viewPatch` in `touchRouting.ts`, used by `TouchLayer.setView`; a pinch still carries the zoom.
- **F3 `SceneSync` compares ids and versions without building strings, applied** (`onChange` 1.34 ms/move in the worst case, over the 1 ms line). A snapshot of ids and a `Float64Array` of versions replaces the 640-string signature; the snapshot of what was sent is still taken at send time, so in-place mutation of a stroke being drawn is still detected (test). Measured: 2000 unchanged `notify` calls over 640 elements take 10.5 ms median now, 68 to 80 ms before (the plan guessed 30x; it is 7x, so `NOTIFY_BUDGET_MS_PER_2000` is 30, three times the new median). The saving is small (about 5 microseconds a call, 0.3 ms/move at 6x) but it is on every pen point.
- **F4 gates on the `DraftBar` scans, applied.** `useDraftOps` and `useSelectedOps` skip an event whose elements array (and selection object) are the identical references as the last one. Safe because drafts only enter or leave through `updateScene({ elements })`, which replaces the array.
- **F2 hidden overlay stops following scroll, applied** (6 percent, under the bar, free). `ChunkOverlay` subscribes to scroll only while the boxes are drawn and resyncs when they show.
- Step 5 contingency (throttle `notify` while the pen is down): not needed, `onChange` is under budget.
- Not changed: ToolRail, railStore, TopBar status, crop sync, ops socket, chunk refresh (noise), `EXCALIDRAW_THROTTLE_RENDER`.

## Dev vs production
The owner serves the tablet with `make serve`, which is a production build; `make dev-web` (Vite dev) is for development. Judge only a production build: Excalidraw's dev build is slower than production for stock too. At 100 percent (fixture, 6x, after the fixes) our app is +3 to +8 ms main/move above stock in dev (production: +2 to +5), within a similar ratio:
**stroke**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs stock |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.8 | 33.3 | 2.0 | 0.00 | 32.4 | 14.2 | - |
| built | 16.7 | 16.8 | 16.8 | 2.0 | 0.73 | 35.6 | 17.9 | +3.2 |

**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs stock |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.7 | 16.8 | 0.0 | 0.00 | 34.1 | 11.9 | - |
| built | 16.7 | 16.7 | 16.8 | 0.0 | 0.56 | 39.5 | 15.4 | +5.4 |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs stock |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 16.8 | 16.8 | 0.0 | 0.00 | 29.2 | 10.5 | - |
| built | 16.7 | 16.7 | 16.8 | 0.0 | 0.51 | 37.7 | 14.5 | +8.5 |

At zoom 0.1 with all 633 elements on screen, **stock Excalidraw's own dev build is already at p95 100 ms with 26 to 44 long tasks per run** and ours matches it:
**pan-wheel**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs stock |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 100.0 | 116.7 | 26.2 | 0.00 | 55.9 | 38.8 | - |
| built | 16.7 | 100.1 | 133.2 | 27.2 | 0.56 | 62.6 | 43.3 | +6.8 |

**pan-touch**

| variant | p50 ms | p95 ms | p99 ms | long/run | onChange ms/move | main ms/move | script | vs stock |
|---|---|---|---|---|---|---|---|---|
| stock | 16.7 | 116.7 | 116.8 | 44.0 | 0.01 | 83.6 | 61.5 | - |
| built | 16.7 | 116.7 | 133.4 | 44.0 | 0.52 | 93.8 | 66.1 | +10.2 |

An early run (before the view was equalised) suggested the app was five times slower than stock in dev; that was the app drawing all elements while stock drew fourteen, and, for the finger pan, the per-frame `zoom` object (about 60 ms/move of 156 in dev, which is why F5 matters most in a dev build). React 19.2's dev-only render logging (`logComponentRender`, prop diffing) dominates dev profiles of both pages.

## Not changed
Pressures and `simulatePressure=false` (no element or restore code touched), the pen-feel patch, autosave durability (same ids, same order, same versions count as the same scene; the in-place mutation case is a test and the 409, idempotency-key and delta tests are unchanged), deep links, `EXCALIDRAW_THROTTLE_RENDER` (stays on), the look of the paper (see F1) and `DESIGN.md`.

## How to run the probe
One-time: `npm i --prefix /tmp/claude-1000/pw-174 playwright-core` (`PW_DIR` overrides; Chromium is `/usr/bin/chromium`, headless, software raster, so GPU raster on a tablet is not modelled).
1. Throwaway API: `cd server && INKBRIDGE_DATA_DIR=/tmp/claude-1000/inkbridge-174 INKBRIDGE_DB=/tmp/claude-1000/inkbridge-174/ink.db INKBRIDGE_DEVICE_LOG=1 uv run uvicorn inkbridge.api:app --port 8101`; seed `uv run python ../scripts/load_fixture.py --api http://127.0.0.1:8101 --canvas fixture-real` (prints the id) and `POST /documents` for an empty canvas.
2. `cd web && PERF_OUT=/tmp/claude-1000/inkbridge-174/dist-perf npx vite build -c scripts/perf/vite.perf.config.ts && npx vite preview -c scripts/perf/vite.perf.config.ts` (port 5191; `npx vite -c scripts/perf/vite.perf.config.ts` for the dev build).
3. `npm run perf -- --base http://127.0.0.1:5191 --canvas <fixture> --empty <empty> --variants stock,built,off:dots,off:overlay,off:drafts,off:autosave --view origin --runs 5 --throttle 6 --out /tmp/claude-1000/inkbridge-174/x.json`. Variants: `stock`, `stock-transparent`, `built`, `off:<flags>` joined by `+` (`dots rail railstore topbar overlay drafts crops ops refresh autosave touch`, plus the probes `touchzoom touchcap touchbare nostrict`). `--view origin|fit`, `--rate N` input events per frame.
4. The guard: `npm run perf -- --guard --base http://127.0.0.1:5191 --canvas <fixture> --empty <empty>` (exit 1 when built is over 20 percent + 2 ms of stock at p95 or `onChange` is over `ONCHANGE_BUDGET_MS`). Frame p95 is quantised to 16.7 ms steps, so on a loaded machine one slow frame can fail it: re-run on a quiet machine before believing a failure. `web/tests/perfHarness.test.ts` keeps the patches from drifting; `sceneSync.test.ts` guards the `notify` cost.

## Tablet check
Pending, for the owner (never blocks the PR). On the `make serve` build (production), open `http://<laptop>:8000/?canvas=<id>&devicelog=1` with the server started with `INKBRIDGE_DEVICE_LOG=1`, write for 30 s and pan with one finger and with the wheel or two fingers, then read `data/logs/device.jsonl` (decision 0059): lines `frames.pointer` and `frames.wheel` carry the buckets `le20 le34 le50 le100 gt100 frames` (most frames should be `le20` or `le34`) and `main.gap` the main-thread stalls. Compare with the same run on excalidraw.com in the tablet browser. Visual sign-off: the dots track the ink while panning (none leading or trailing; if they trail by a frame, write the transform synchronously in `onScrollChange` instead), and pen feel, pressure and Accept/Reject are unchanged. Say on the PR which build is run.
