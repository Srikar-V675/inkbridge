import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { fetchTitle } from "../src/app/canvasTitle.ts";
import { createRailStore } from "../src/app/railStore.ts";
import {
  colourNeedsPen, dotStep, HIGHLIGHTER, MIN_DOT_PX, nextZoom, paperDots, PEN, penColours, penIndex, railTool, toolTap,
  undoKey, zoomAbout, ZOOM_MAX, ZOOM_MIN,
} from "../src/app/shellLogic.ts";

describe("dotStep", () => {
  it("doubles the spacing until a dot gap is at least 10 px", () => {
    assert.equal(dotStep(1), 24);
    assert.equal(dotStep(0.4), 48);
    assert.equal(dotStep(0.1), 192);
    assert.equal(dotStep(30), 24);
    for (const z of [0.1, 0.25, 0.4, 0.7, 1, 3]) assert.ok(dotStep(z) * z >= MIN_DOT_PX);
  });
});

describe("paperDots", () => {
  it("is the tile at the origin", () => {
    assert.deepEqual(paperDots({ scrollX: 0, scrollY: 0, zoom: 1 }), { size: 24, x: 0, y: 0 });
  });
  it("never gives a negative offset", () => {
    assert.equal(paperDots({ scrollX: -30, scrollY: 0, zoom: 1 }).x, 18);
  });
  it("scales with zoom", () => {
    const d = paperDots({ scrollX: 10, scrollY: 0, zoom: 2 });
    assert.equal(d.size, 48);
    assert.equal(d.x, 20);
  });
  it("puts a dot at the centre of every scene tile", () => {
    let seed = 7;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
    for (let i = 0; i < 200; i++) {
      const v = { scrollX: (rnd() - 0.5) * 5000, scrollY: (rnd() - 0.5) * 5000, zoom: 0.1 + rnd() * 5 };
      const step = dotStep(v.zoom);
      const k = Math.floor((rnd() - 0.5) * 40);
      const p = k * step + step / 2;
      const d = paperDots(v);
      for (const [scroll, off] of [[v.scrollX, d.x], [v.scrollY, d.y]] as const) {
        const screen = (p + scroll) * v.zoom;
        const r = (((screen - off) % d.size) + d.size) % d.size;
        assert.ok(Math.abs(r - d.size / 2) < 1e-6, `${r} vs ${d.size / 2}`);
      }
    }
  });
});

describe("zoom", () => {
  it("steps by 1.25 and clamps", () => {
    assert.equal(nextZoom(1, 1), 1.25);
    assert.equal(nextZoom(1.25, -1), 1);
    assert.equal(nextZoom(29, 1), ZOOM_MAX);
    assert.equal(nextZoom(0.11, -1), ZOOM_MIN);
  });
  it("zooms about the viewport centre", () => {
    const v = { scrollX: -120, scrollY: 340, zoom: 0.8, width: 1280, height: 800 };
    const z = zoomAbout(v, 2);
    assert.equal(z.zoom, 2);
    assert.ok(Math.abs(v.width / 2 / v.zoom - v.scrollX - (v.width / 2 / z.zoom - z.scrollX)) < 1e-9);
    assert.ok(Math.abs(v.height / 2 / v.zoom - v.scrollY - (v.height / 2 / z.zoom - z.scrollY)) < 1e-9);
  });
});

describe("rail tools", () => {
  it("reads pen and highlighter from the opacity", () => {
    assert.equal(railTool({ activeTool: { type: "freedraw" }, currentItemOpacity: 100 }), "pen");
    assert.equal(railTool({ activeTool: { type: "freedraw" }, currentItemOpacity: 35 }), "highlighter");
    assert.equal(railTool({ activeTool: { type: "selection" }, currentItemOpacity: 100 }), "select");
    assert.equal(railTool({ activeTool: { type: "eraser" }, currentItemOpacity: 100 }), "eraser");
    assert.equal(railTool({ activeTool: { type: "text" }, currentItemOpacity: 100 }), "text");
    assert.equal(railTool({ activeTool: { type: "diamond" }, currentItemOpacity: 100 }), "shapes");
    assert.equal(railTool({ activeTool: { type: "hand" }, currentItemOpacity: 100 }), null);
  });
  it("select is the selection tool (no lasso in Excalidraw 0.18)", () => {
    assert.deepEqual(toolTap("select", "freedraw").tool, { type: "selection" });
  });
  it("shapes cycle from rectangle", () => {
    assert.equal(toolTap("shapes", "freedraw").tool.type, "rectangle");
    assert.equal(toolTap("shapes", "rectangle").tool.type, "ellipse");
    assert.equal(toolTap("shapes", "ellipse").tool.type, "diamond");
    assert.equal(toolTap("shapes", "diamond").tool.type, "arrow");
    assert.equal(toolTap("shapes", "arrow").tool.type, "rectangle");
  });
  it("pen and highlighter set opacity and width", () => {
    assert.deepEqual(toolTap("pen", "selection").patch, { currentItemOpacity: PEN.opacity, currentItemStrokeWidth: PEN.strokeWidth });
    assert.equal(PEN.opacity, 100);
    assert.equal(PEN.strokeWidth, 2);
    assert.deepEqual(toolTap("highlighter", "selection").patch, { currentItemOpacity: 35, currentItemStrokeWidth: 4 });
    assert.deepEqual(HIGHLIGHTER, { opacity: 35, strokeWidth: 4 });
  });
  it("shapes and text do not inherit the highlighter", () => {
    for (const t of ["shapes", "text"] as const) {
      assert.deepEqual(toolTap(t, "freedraw").patch, { currentItemOpacity: 100, currentItemStrokeWidth: 2 });
    }
  });
  it("never touches pressure state", () => {
    for (const t of ["pen", "highlighter", "eraser", "select", "shapes", "text"] as const) {
      for (const key of Object.keys(toolTap(t, "freedraw").patch)) {
        assert.ok(key === "currentItemOpacity" || key === "currentItemStrokeWidth", key);
      }
    }
  });
  it("a colour pick leaves eraser, selection and hand for the pen", () => {
    assert.ok(colourNeedsPen("eraser"));
    assert.ok(colourNeedsPen("selection"));
    assert.ok(colourNeedsPen("hand"));
    assert.ok(!colourNeedsPen("freedraw"));
    assert.ok(!colourNeedsPen("text"));
  });
});

describe("pens and undo keys", () => {
  it("finds a pen colour ignoring case", () => {
    assert.equal(penIndex("#2f55b8", ["#2E2D2B", "#2F55B8", "#A63D2A"]), 1);
    assert.equal(penIndex("#000000", ["#2E2D2B"]), -1);
  });
  it("reads pen colours from custom properties, trimmed", () => {
    const seen: string[] = [];
    const out = penColours((n) => (seen.push(n), ` ${n}-v `));
    assert.deepEqual(seen, ["--color-pen-charcoal", "--color-pen-blue", "--color-pen-brick"]);
    assert.deepEqual(out, ["--color-pen-charcoal-v", "--color-pen-blue-v", "--color-pen-brick-v"]);
  });
  it("builds undo and redo key events", () => {
    const redo = undoKey("redo", false);
    assert.equal(redo.shiftKey, true);
    assert.equal(redo.ctrlKey, true);
    assert.equal(redo.metaKey, false);
    const undo = undoKey("undo", true);
    assert.equal(undo.shiftKey, false);
    assert.equal(undo.metaKey, true);
    assert.equal(undo.ctrlKey, false);
    assert.equal(undo.key, "z");
  });
});

const PENS = ["#2E2D2B", "#2F55B8", "#A63D2A"];
const NEVER = "NEVER";

function fakeApi(start: Record<string, unknown> = {}) {
  let state: Record<string, unknown> = {
    activeTool: { type: "selection" },
    currentItemOpacity: 100,
    currentItemStrokeColor: "#000000",
    scrollX: 0,
    scrollY: 0,
    zoom: { value: 1 },
    width: 1000,
    height: 600,
    ...start,
  };
  const subs = new Set<(els: unknown[], a: Record<string, unknown>) => void>();
  const calls: { tool: unknown[]; scene: Record<string, unknown>[] } = { tool: [], scene: [] };
  const api = {
    getAppState: () => state,
    onChange: (cb: (els: unknown[], a: Record<string, unknown>) => void) => (subs.add(cb), () => void subs.delete(cb)),
    setActiveTool: (t: unknown) => void calls.tool.push(t),
    updateScene: (s: Record<string, unknown>) => void calls.scene.push(s),
  };
  return {
    api: api as never,
    calls,
    subs,
    set(next: Record<string, unknown>) {
      state = { ...state, ...next };
      subs.forEach((cb) => cb([], state));
    },
  };
}

function fakeEnv() {
  const events: KeyboardEventInit[] = [];
  return {
    events,
    env: {
      never: NEVER,
      mac: false,
      container: () => ({ dispatchEvent: (e: unknown) => (events.push(e as KeyboardEventInit), true) }),
      makeKey: (init: KeyboardEventInit) => init as never,
      frame: () => () => {},
    },
  };
}

describe("createRailStore", () => {
  it("starts with the pen and charcoal, once, and subscribes", () => {
    const f = fakeApi();
    const { env } = fakeEnv();
    const store = createRailStore(f.api, PENS, env as never);
    assert.deepEqual(f.calls.tool, [{ type: "freedraw" }]);
    assert.equal(f.calls.scene.length, 1);
    assert.deepEqual((f.calls.scene[0].appState as Record<string, unknown>).currentItemStrokeColor, "#2E2D2B");
    assert.equal(f.subs.size, 1);
    store.dispose();
    assert.equal(f.subs.size, 0);
  });

  it("waits for Excalidraw to finish loading before choosing the pen", () => {
    const f = fakeApi({ isLoading: true });
    const frames: (() => void)[] = [];
    const env = { ...fakeEnv().env, frame: (cb: () => void) => (frames.push(cb), () => {}) };
    const store = createRailStore(f.api, PENS, env as never);
    assert.deepEqual(f.calls.tool, []);
    assert.equal(frames.length, 1);
    frames.shift()!(); // still loading
    assert.deepEqual(f.calls.tool, []);
    f.set({ isLoading: false });
    frames.shift()!();
    assert.deepEqual(f.calls.tool, [{ type: "freedraw" }]);
    assert.equal(f.calls.scene.length, 1);
    assert.equal(frames.length, 0);
    store.dispose();
  });

  it("keeps a selection made by a deep link: the pen is not chosen over it", () => {
    const f = fakeApi({ selectedElementIds: { a: true } });
    createRailStore(f.api, PENS, fakeEnv().env as never);
    assert.deepEqual(f.calls.tool, []);
    assert.equal(f.calls.scene.length, 1); // the charcoal colour is still set
  });

  it("does not pick the pen when the route has a chunk link, even with nothing selected yet", () => {
    const f = fakeApi();
    createRailStore(f.api, PENS, { ...fakeEnv().env, deepLink: true } as never);
    assert.deepEqual(f.calls.tool, []);
    assert.equal(f.calls.scene.length, 1);
  });

  it("keeps the same snapshot while nothing the rail shows changes", () => {
    const f = fakeApi({ activeTool: { type: "freedraw" }, currentItemStrokeColor: "#2E2D2B" });
    const { env } = fakeEnv();
    const store = createRailStore(f.api, PENS, env as never);
    const first = store.get();
    let runs = 0;
    store.subscribe(() => runs++);
    for (let i = 0; i < 100; i++) f.set({ scrollX: i });
    assert.equal(runs, 0);
    assert.equal(store.get(), first);
    f.set({ activeTool: { type: "eraser" } });
    assert.equal(runs, 1);
    assert.equal(store.get().tool, "eraser");
    assert.notEqual(store.get(), first);
  });

  it("highlighter sets freedraw at 35 percent, width 4, without history", () => {
    const f = fakeApi();
    const store = createRailStore(f.api, PENS, fakeEnv().env as never);
    f.calls.tool.length = 0;
    f.calls.scene.length = 0;
    store.tap("highlighter");
    assert.deepEqual(f.calls.tool, [{ type: "freedraw" }]);
    assert.deepEqual(f.calls.scene, [{ appState: { currentItemOpacity: 35, currentItemStrokeWidth: 4 }, captureUpdate: NEVER }]);
  });

  it("a pen colour sets the stroke colour, via the pen when another tool is active", () => {
    const f = fakeApi({ activeTool: { type: "eraser" } });
    const store = createRailStore(f.api, PENS, fakeEnv().env as never);
    f.calls.tool.length = 0;
    f.calls.scene.length = 0;
    store.setPen(1);
    assert.deepEqual(f.calls.tool, [{ type: "freedraw" }]);
    assert.deepEqual(f.calls.scene, [{ appState: { currentItemStrokeColor: "#2F55B8" }, captureUpdate: NEVER }]);
    f.set({ activeTool: { type: "freedraw" } });
    f.calls.tool.length = 0;
    store.setPen(2);
    assert.deepEqual(f.calls.tool, []);
  });

  it("zoom buttons zoom about the centre without history", () => {
    const f = fakeApi({ zoom: { value: 1 }, scrollX: 10, scrollY: 20 });
    const store = createRailStore(f.api, PENS, fakeEnv().env as never);
    f.calls.scene.length = 0;
    store.zoomBy(1);
    const z = zoomAbout({ scrollX: 10, scrollY: 20, zoom: 1, width: 1000, height: 600 }, 1.25);
    assert.deepEqual(f.calls.scene, [{ appState: { zoom: { value: 1.25 }, scrollX: z.scrollX, scrollY: z.scrollY }, captureUpdate: NEVER }]);
  });

  it("undo and redo send a key event to the canvas container", () => {
    const f = fakeApi();
    const e = fakeEnv();
    const store = createRailStore(f.api, PENS, e.env as never);
    store.undo();
    store.redo();
    assert.equal(e.events[0].key, "z");
    assert.equal(e.events[0].shiftKey, false);
    assert.equal(e.events[1].key, "Z");
    assert.equal(e.events[1].shiftKey, true);
  });
});

describe("fetchTitle", () => {
  const real = globalThis.fetch;
  afterEach(() => void (globalThis.fetch = real));
  const stub = (f: (url: string) => Promise<unknown>) => void (globalThis.fetch = f as never);

  it("reads the one canvas, not the whole list", async () => {
    const urls: string[] = [];
    stub(async (url) => (urls.push(url), { ok: true, json: async () => ({ id: "b", title: "Linear models" }) }));
    assert.equal(await fetchTitle("b"), "Linear models");
    assert.deepEqual(urls, ["/documents/b"]);
  });
  it("encodes the id", async () => {
    const urls: string[] = [];
    stub(async (url) => (urls.push(url), { ok: false, json: async () => ({}) }));
    await fetchTitle("a/b");
    assert.deepEqual(urls, ["/documents/a%2Fb"]);
  });
  it("falls back to the id when the canvas is unknown or has no title", async () => {
    stub(async () => ({ ok: false, json: async () => ({ detail: "document not found" }) }));
    assert.equal(await fetchTitle("zzz"), "zzz");
    stub(async () => ({ ok: true, json: async () => ({ id: "c", title: "" }) }));
    assert.equal(await fetchTitle("c"), "c");
  });
  it("never throws", async () => {
    stub(async () => Promise.reject(new Error("offline")));
    assert.equal(await fetchTitle("x"), "x");
    stub(async () => ({ ok: true, json: async () => [] }));
    assert.equal(await fetchTitle("x"), "x");
    stub(async () => ({ ok: true, json: async () => null }));
    assert.equal(await fetchTitle("x"), "x");
  });
});
