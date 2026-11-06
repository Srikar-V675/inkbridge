// INK-174 bisect driver: frame times and long tasks while a synthetic pen stroke or pan runs under
// CPU throttle, for stock Excalidraw, the app as built and the app with one layer switched off.
// Dev tooling only. playwright-core is not a dependency: `npm i --prefix /tmp/claude-1000/pw-174 playwright-core`
// (PW_DIR overrides). Needs a built perf bundle served by `vite preview -c scripts/perf/vite.perf.config.ts`.
//
//   node scripts/perf/bisect.mjs --base http://127.0.0.1:5191 --canvas <id> [--empty <id>]
//     [--variants stock,built,off:dots,off:dots+overlay,stock-transparent] [--scenarios stroke,pan-wheel,pan-touch]
//     [--runs 5] [--throttle 6] [--rate 1] [--view fit|origin] [--out file.json] [--guard]
//
// Events are paced one per animation frame, so a dropped frame shows up as a long delta. Stroke runs
// write real elements (autosave runs against the throwaway database); each stroke is undone after it.
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { budgetVerdict, OFF_FLAGS, summarise } from "./variants.ts";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : true]);
    return acc;
  }, []),
);
const base = args.base ?? "http://127.0.0.1:5191";
const canvases = { fixture: args.canvas, ...(args.empty ? { empty: args.empty } : {}) };
const runs = Number(args.runs ?? 5);
const throttle = Number(args.throttle ?? 6);
const guard = Boolean(args.guard);
const view = String(args.view ?? "fit");
const rate = Number(args.rate ?? 1); // input events per frame (a 240 Hz stylus sends four)
const scenarios = guard ? ["stroke", "pan-touch"] : String(args.scenarios ?? "stroke,pan-wheel,pan-touch").split(",");
const variants = guard ? ["stock", "built"] : String(args.variants ?? "stock,built").split(",");
if (!args.canvas) throw new Error("--canvas <id> is required");

const pwDir = process.env.PW_DIR ?? "/tmp/claude-1000/pw-174";
const { chromium } = createRequire(join(pwDir, "package.json"))("playwright-core");

// Every shell layer off except the touch router (the probes after it are not layers).
const ALL_OFF = OFF_FLAGS.slice(0, OFF_FLAGS.indexOf("touch")).join("+");
const wantsEmpty = (v) => v === "stock" || v === "built" || v === `off:${ALL_OFF}` || args["empty-all"];

function url(variant, canvas, scenario) {
  if (variant.startsWith("stock")) {
    const q = new URLSearchParams({ canvas });
    q.set("tool", scenario === "stroke" ? "freedraw" : "hand");
    if (scenario === "stroke") q.set("pen", "1");
    if (variant === "stock-transparent") {
      q.set("transparent", "1");
      q.set("pen", "1");
    }
    return `${base}/perf/stock.html?${q}`;
  }
  const q = new URLSearchParams({ canvas });
  if (variant.startsWith("off:")) q.set("off", variant.slice(4));
  return `${base}/?${q}`;
}

/** Main-thread seconds so far: whole tasks, script, layout, style recalculation. */
async function cpu(cdp) {
  const { metrics } = await cdp.send("Performance.getMetrics");
  const m = Object.fromEntries(metrics.map((x) => [x.name, x.value]));
  return { task: m.TaskDuration, script: m.ScriptDuration, layout: m.LayoutDuration, style: m.RecalcStyleDuration };
}

const raf = () => new Promise((r) => requestAnimationFrame(() => r()));

async function openPage(browser, variant, canvas, scenario) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, hasTouch: scenario === "pan-touch" });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.__rec = { on: false };
    window.__frames = [];
    window.__long = [];
    window.__onChangeMs = [];
    let prev = 0;
    const loop = (t) => {
      if (window.__rec.on) {
        if (prev) window.__frames.push(t - prev);
        prev = t;
      } else prev = 0;
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
    new PerformanceObserver((l) => {
      if (window.__rec.on) for (const e of l.getEntries()) window.__long.push(e.duration);
    }).observe({ type: "longtask" });
  });
  await page.goto(url(variant, canvas, scenario), { waitUntil: "load" });
  if (variant.startsWith("stock")) await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
  else {
    await page.waitForSelector(".excalidraw canvas", { timeout: 60000 });
    await page.waitForFunction(() => !document.querySelector(".ink-shell__loading") && window.__api, null, { timeout: 60000 });
  }
  await page.waitForTimeout(1500);
  // Same view for every page: the app fits all ink on first open, stock opens at 100 percent, and the
  // number of elements on screen decides how much each frame draws. `--view origin` is 100 percent at 0,0.
  await page.evaluate((v) => {
    const api = window.__api;
    if (v === "origin") api.updateScene({ appState: { scrollX: 0, scrollY: 0, zoom: { value: 1 } } });
    else if (api.getSceneElements().length) api.scrollToContent(undefined, { fitToViewport: true, viewportZoomFactor: 0.9, maxZoom: 1, animate: false });
  }, view);
  await page.waitForTimeout(800);
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: throttle });
  await cdp.send("Performance.enable");
  return { context, page, cdp };
}

const drivers = {
  stroke: { moves: 200, async run({ page, cdp }) {
    const pen = { button: "left", pointerType: "pen" };
    const at = (i) => ({ x: 320 + (i / 199) * 780, y: 400 + 150 * Math.sin(i / 20) });
    const step = (i) => (i % rate === 0 ? page.evaluate(raf) : null);
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...at(0), pointerType: "pen" });
    await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", ...at(0), ...pen, buttons: 1, clickCount: 1, force: 0.5 });
    await step(0);
    for (let i = 1; i < 199; i++) {
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...at(i), ...pen, buttons: 1, force: 0.3 + 0.6 * ((i % 40) / 40) });
      await step(i);
    }
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...at(199), ...pen, buttons: 0, clickCount: 1 });
    await step(0);
  }, async after({ page }) {
    await page.keyboard.press("Control+z");
    await page.waitForTimeout(300);
  } },
  "pan-wheel": { moves: 100, async run({ page, cdp }) {
    for (let i = 0; i < 100; i++) {
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseWheel", x: 640, y: 400, deltaX: 20, deltaY: 20 });
      if (i % rate === 0) await page.evaluate(raf);
    }
  } },
  "pan-touch": { moves: 100, async run({ page, cdp }) {
    const pt = (i) => [{ x: 300 + i * 6, y: 100 + i * 6, id: 1 }];
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: pt(0) });
    await page.evaluate(raf);
    for (let i = 1; i <= 100; i++) {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: pt(i) });
      if (i % rate === 0) await page.evaluate(raf);
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.evaluate(raf);
  } },
};

async function measure(handle, scenario) {
  const { page } = handle;
  const d = drivers[scenario];
  const state = () =>
    page.evaluate(() => {
      const s = window.__api.getAppState();
      return { scrollX: s.scrollX, scrollY: s.scrollY, n: window.__api.getSceneElements().length };
    });
  const view = await state();
  const zoom = await page.evaluate(() => window.__api.getAppState().zoom.value);
  console.error(`  view: zoom ${zoom.toFixed(3)}, scroll ${view.scrollX.toFixed(0)},${view.scrollY.toFixed(0)}, ${view.n} elements`);
  const reset = () => page.evaluate((v) => window.__api.updateScene({ appState: v }), view);
  const out = { noEffect: 0, cpu: { task: 0, script: 0, layout: 0, style: 0, wall: 0 }, deltas: [], longtasks: [], onChange: [], moves: 0, runs: 0 };
  for (let r = 0; r <= runs; r++) {
    await page.evaluate(() => ((window.__frames = []), (window.__long = []), (window.__onChangeMs = []), (window.__rec.on = true)));
    const c0 = { ...(await cpu(handle.cdp)), wall: performance.now() / 1000 };
    await d.run(handle);
    const c1 = { ...(await cpu(handle.cdp)), wall: performance.now() / 1000 };
    const after = await state();
    // Proof the driver did something: a pan moves the view, a stroke adds one element.
    const moved = Math.abs(after.scrollX - view.scrollX) + Math.abs(after.scrollY - view.scrollY);
    if (scenario === "stroke" ? after.n !== view.n + 1 : moved < 1) out.noEffect = (out.noEffect ?? 0) + 1;
    const got = await page.evaluate(() => ((window.__rec.on = false), { f: window.__frames, l: window.__long, o: window.__onChangeMs }));
    if (r > 0) { // run 0 is the warm-up
      out.deltas.push(...got.f);
      out.longtasks.push(...got.l);
      out.onChange.push(...got.o);
      for (const k of Object.keys(out.cpu)) out.cpu[k] += (c1[k] - c0[k]) * 1000; // ms, wall time under throttle
      out.moves += d.moves;
      out.runs += 1;
    }
    if (d.after) await d.after(handle);
    await reset();
    await page.waitForTimeout(400);
  }
  return out;
}

const fmt = (n) => (Number.isFinite(n) ? n.toFixed(1) : "-");
const raw = {};
const rows = [];
const browser = await chromium.launch({ executablePath: "/usr/bin/chromium", args: ["--no-sandbox"] });
try {
  for (const variant of variants) {
    for (const [cname, canvas] of Object.entries(canvases)) {
      if (cname === "empty" && !guard && !wantsEmpty(variant)) continue;
      for (const scenario of scenarios) {
        // Stroke runs last on a page and the touch page needs touch emulation, so each scenario gets its own page.
        const handle = await openPage(browser, variant, canvas, scenario);
        try {
          const m = await measure(handle, scenario);
          ((raw[variant] ??= {})[cname] ??= {})[scenario] = m;
          const s = summarise(m);
          rows.push({ variant, cname, scenario, s, cpu: Object.fromEntries(Object.entries(m.cpu).map(([k, v]) => [k, v / m.moves])) });
          if (m.noEffect) console.error(`WARNING ${variant} ${cname} ${scenario}: ${m.noEffect} run(s) had no effect (no pan, no stroke)`);
          console.error(`${variant} ${cname} ${scenario}: p50 ${fmt(s.p50)} p95 ${fmt(s.p95)} p99 ${fmt(s.p99)} main/move ${(m.cpu.task / m.moves).toFixed(2)} long ${fmt(s.longPerRun)} onChange ${s.onChangeMsPerMove.toFixed(2)}`);
        } finally {
          await handle.context.close();
        }
      }
    }
  }
} finally {
  await browser.close();
}

console.log(`throttle ${throttle}x, ${rate} event(s) per frame, ${runs} measured runs after 1 warm-up, headless Chromium (software raster), events paced one per frame; stroke runs autosave to the throwaway database\n`);
console.log("| variant | canvas | scenario | p50 ms | p95 ms | p99 ms | long tasks/run | onChange ms/move | main ms/move (script, layout, style) | wall ms/move |");
console.log("|---|---|---|---|---|---|---|---|---|---|");
for (const { variant, cname, scenario, s, cpu: c } of rows) {
  console.log(`| ${variant} | ${cname} | ${scenario} | ${fmt(s.p50)} | ${fmt(s.p95)} | ${fmt(s.p99)} | ${fmt(s.longPerRun)} | ${s.onChangeMsPerMove.toFixed(2)} | ${c.task.toFixed(2)} (${c.script.toFixed(2)}, ${c.layout.toFixed(2)}, ${c.style.toFixed(2)}) | ${c.wall.toFixed(1)} |`);
}
if (args.out) writeFileSync(args.out, JSON.stringify({ throttle, runs, raw }, null, 1));

if (guard) {
  let ok = true;
  for (const cname of Object.keys(canvases)) {
    for (const scenario of scenarios) {
      const pick = (v) => rows.find((r) => r.variant === v && r.cname === cname && r.scenario === scenario)?.s;
      const v = budgetVerdict({ built: pick("built"), stock: pick("stock") });
      console.log(`guard ${cname} ${scenario}: ${v.ok ? "ok" : "FAIL " + v.reasons.join("; ")}`);
      ok &&= v.ok;
    }
  }
  process.exit(ok ? 0 : 1);
}
