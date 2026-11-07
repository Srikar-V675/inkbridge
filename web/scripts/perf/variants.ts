// Pure helpers for the write and pan bisect (INK-174, decision 0073). Node-loadable, no Vite import.
// Dev tooling only: the patches below are applied by scripts/perf/vite.perf.config.ts, never by the
// shipped build, so the app carries no perf switches.

export const OFF_FLAGS = ["dots", "rail", "railstore", "topbar", "overlay", "drafts", "crops", "ops", "refresh", "autosave", "touch", "touchzoom", "touchcap", "touchbare", "nostrict", "throttle", "fastink"] as const;
export type OffFlag = (typeof OFF_FLAGS)[number];

/** find/replace on a file under web/src; `{{OFF}}` in `replace` is the flag name. `find` must occur exactly once. */
export interface Patch {
  file: string;
  find: string;
  replace: string;
}

/** Per pen move or pan frame, summed over every onChange subscriber, at 6x CPU throttle. Twice the post-fix median on the fixture (0.45 to 1.1 ms/move over stroke and pans, about 0.8), rounded up to 0.5 (INK-174, decision 0073). */
export const ONCHANGE_BUDGET_MS = 2;

/** Component off = render null. The wrapper is hoisted above the renamed original. */
function wrap(file: string, name: string, flag: OffFlag): Patch {
  const head = `export function ${name}(`;
  return {
    file,
    find: head,
    replace: `export function ${name}(p) { return __off("${flag}") ? null : ${name}Real(p); }\nfunction ${name}Real(`,
  };
}

/** Method or function off = return at once. */
function early(file: string, find: string, flag: OffFlag, ret = ""): Patch {
  return { file, find, replace: `${find} if (__off("${flag}")) return${ret ? ` ${ret}` : ""};` };
}

function setViewProbe(flag: OffFlag, appState: string, capture: string): Patch {
  const find = "setView: (v) =>";
  return {
    file: "app/TouchLayer.tsx",
    find,
    replace: `${find} __off("${flag}") ? api.updateScene({ appState: ${appState}${capture ? `, ${capture}` : ""} }) :`,
  };
}

export const PATCHES: Record<OffFlag, Patch[]> = {
  dots: [wrap("app/PaperDots.tsx", "PaperDots", "dots")],
  rail: [wrap("app/ToolRail.tsx", "ToolRail", "rail"), wrap("app/ZoomControl.tsx", "ZoomControl", "rail")],
  railstore: [
    {
      file: "app/railStore.ts",
      find: "const offChange = api.onChange(refresh);",
      replace: 'const offChange = __off("railstore") ? () => {} : api.onChange(refresh);',
    },
  ],
  topbar: [wrap("app/TopBar.tsx", "TopBar", "topbar")],
  overlay: [wrap("chunks/ChunkOverlay.tsx", "ChunkOverlay", "overlay")],
  drafts: [wrap("drafts/DraftBar.tsx", "DraftBar", "drafts")],
  crops: [
    early("sync/cropSync.ts", "start(pollMs = 30_000) {", "crops"),
    early("sync/cropSync.ts", "  request() {", "crops"),
    early("sync/cropSync.ts", "  activity() {", "crops"),
    early("sync/cropSync.ts", "setDrawing(down: boolean) {", "crops"),
  ],
  ops: [early("sync/opsSocket.ts", "  start() {", "ops")],
  refresh: [early("sync/chunkRefresh.ts", "    fire() {", "refresh")],
  autosave: [early("sync/sceneSync.ts", "notify(elements: readonly SceneElement[]): boolean {", "autosave", "false")],
  touch: [wrap("app/TouchLayer.tsx", "TouchRouting", "touch")],
  // Not layers but probes of the finger-pan write (touchzoom: no zoom in the patch, touchcap: no captureUpdate, touchbare: neither).
  touchzoom: [setViewProbe("touchzoom", "{ scrollX: v.scrollX, scrollY: v.scrollY }", "captureUpdate: CaptureUpdateAction.NEVER")],
  touchcap: [setViewProbe("touchcap", "{ scrollX: v.scrollX, scrollY: v.scrollY, zoom: { value: v.zoom as never } }", "")],
  touchbare: [setViewProbe("touchbare", "{ scrollX: v.scrollX, scrollY: v.scrollY }", "")],
  // Dev builds double-invoke renders under StrictMode (the stock page has none): off = render without it.
  // Excalidraw's render throttle (INK-101) delays drawing the stroke in progress by a frame: off = render on every event (INK-181).
  throttle: [{ file: "lib/excalidrawEnv.ts", find: "w.EXCALIDRAW_THROTTLE_RENDER = true;", replace: 'w.EXCALIDRAW_THROTTLE_RENDER = !__off("throttle");' }],
  // The INK-181 fast ink layer and pen-sample collector (the patched Excalidraw then falls back to one point per event).
  fastink: [wrap("ink/FastInk.tsx", "FastInk", "fastink")],
  nostrict: [
    {
      file: "main.tsx",
      find: "root.render(<StrictMode><Root /></StrictMode>)",
      replace: 'root.render(__off("nostrict") ? <Root /> : <StrictMode><Root /></StrictMode>)',
    },
  ],
};

/** The two strings in App.tsx the perf plugin swaps to time every onChange subscriber. Keep them unchanged. */
export const WRAP_PATTERNS = [
  { find: "excalidrawAPI={onApi}", replace: "excalidrawAPI={perfApi(onApi)}" },
  { find: "onChange={onChange as never}", replace: "onChange={perfChange(onChange) as never}" },
];

export interface Summary {
  p50: number;
  p95: number;
  p99: number;
  longPerRun: number;
  onChangeMsPerMove: number;
  /** Measured runs in which the driver did nothing (no stroke drawn, no pan): such numbers mean nothing. */
  noEffect?: number;
}

/** Nearest-rank percentile; NaN for no data. */
export function percentile(xs: number[], p: number): number {
  if (xs.length === 0) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.ceil(p * s.length - 1e-9) - 1))];
}

export function summarise(i: { deltas: number[]; longtasks: number[]; onChange: number[]; moves: number; runs: number; noEffect?: number }): Summary {
  const sum = i.onChange.reduce((a, b) => a + b, 0);
  return {
    p50: percentile(i.deltas, 0.5),
    p95: percentile(i.deltas, 0.95),
    p99: percentile(i.deltas, 0.99),
    longPerRun: i.runs > 0 ? i.longtasks.length / i.runs : NaN,
    onChangeMsPerMove: i.moves > 0 ? sum / i.moves : NaN,
    ...(i.noEffect !== undefined && { noEffect: i.noEffect }),
  };
}

/**
 * Built must stay within 20 percent (+ 2 ms of 60 Hz frame quantisation) of stock at p95 and under the
 * onChange budget. A missing number (NaN compares false against any limit) or a scenario in which the
 * driver did nothing is a failure, never a pass.
 */
export function budgetVerdict(i: { built: Summary; stock: Summary; budgetMs?: number }): { ok: boolean; reasons: string[] } {
  const reasons: string[] = [];
  for (const [name, s] of [["built", i.built], ["stock", i.stock]] as const) {
    if (!Number.isFinite(s.p95)) reasons.push(`${name} p95 is not a number (no frames recorded)`);
    if (name === "built" && !Number.isFinite(s.onChangeMsPerMove)) reasons.push("built onChange cost is not a number (no moves recorded)");
    if ((s.noEffect ?? 0) > 0) reasons.push(`${name} had ${s.noEffect} run(s) with no effect (no stroke drawn, no pan)`);
  }
  if (Number.isFinite(i.built.p95) && Number.isFinite(i.stock.p95)) {
    const limit = i.stock.p95 * 1.2 + 2;
    if (i.built.p95 > limit) reasons.push(`p95 ${i.built.p95.toFixed(1)} ms is over ${limit.toFixed(1)} ms (stock ${i.stock.p95.toFixed(1)} x 1.2 + 2)`);
  }
  const budget = i.budgetMs ?? ONCHANGE_BUDGET_MS;
  if (Number.isFinite(i.built.onChangeMsPerMove) && i.built.onChangeMsPerMove > budget) {
    reasons.push(`onChange ${i.built.onChangeMsPerMove.toFixed(2)} ms/move is over ${budget} ms`);
  }
  return { ok: reasons.length === 0, reasons };
}
