import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createPropsStore } from "../src/app/props/propsStore.ts";
import { controlsFor } from "../src/app/props/propsLogic.ts";

const NEVER = "NEVER";
const NOW = "NOW";
const base = { version: 5, versionNonce: 1, updated: 1, strokeColor: "#000000", backgroundColor: "transparent", fillStyle: "hachure", strokeWidth: 2, strokeStyle: "solid", roughness: 1, opacity: 100, roundness: null, isDeleted: false };
const el = (id: string, type: string, extra: Record<string, unknown> = {}) => ({ ...base, id, type, ...extra });

type Rec = Record<string, unknown>;
function fake(start: Rec = {}, scene: Rec[] = []) {
  let state: Rec = {
    activeTool: { type: "freedraw" },
    selectedElementIds: {},
    cursorButton: "up",
    editingTextElement: null,
    currentItemStrokeColor: "#2e2d2b",
    currentItemStrokeWidth: 2,
    currentItemOpacity: 100,
    ...start,
  };
  let elements = scene;
  const subs = new Set<(els: unknown[], a: Rec) => void>();
  const calls = { scene: [] as Rec[], read: 0, order: [] as string[] };
  const api = {
    getAppState: () => state,
    getSceneElementsIncludingDeleted: () => ((calls.read++), elements),
    onChange: (cb: (els: unknown[], a: Rec) => void) => (subs.add(cb), () => void subs.delete(cb)),
    updateScene: (s: Rec) => void (calls.scene.push(s), calls.order.push("update")),
  };
  return {
    api: api as never,
    calls,
    subs,
    set(next: Rec, els?: Rec[]) {
      state = { ...state, ...next };
      if (els) elements = els;
      subs.forEach((cb) => cb(elements, state));
    },
  };
}

const keys: KeyboardEventInit[] = [];
let n = 0;
const measure = (line: string, size: number) => line.length * size * 0.5;
const loads: [number, number][] = [];
const mkEnv = (f?: { calls: { order: string[] } }) => ({
  never: NEVER, immediately: NOW, mac: false,
  container: () => ({ dispatchEvent: (e: unknown) => (keys.push(e as KeyboardEventInit), true) }),
  makeKey: (i: KeyboardEventInit) => i as never,
  nonce: () => 7000 + n++, now: () => 1700000000000,
  measure,
  loadFont: async (fam: number, size: number) => void (loads.push([fam, size]), f?.calls.order.push("load")),
});

describe("tool source", () => {
  it("shows the tool rows and writes the tool defaults without history", () => {
    const f = fake({ activeTool: { type: "rectangle" }, currentItemStrokeColor: "#2F55B8" });
    const store = createPropsStore(f.api, mkEnv() as never);
    const s = store.get();
    assert.equal(s.source, "tool");
    assert.deepEqual(s.controls, controlsFor(["rectangle"]));
    assert.equal(s.values.stroke, "#2f55b8");
    assert.equal(s.title, "Rectangle tool");
    assert.equal(s.layers, false);
    store.set("width", 4);
    assert.equal(f.calls.scene.length, 1);
    assert.deepEqual(f.calls.scene[0], { appState: { currentItemStrokeWidth: 4 }, captureUpdate: NEVER });
    assert.ok(!("elements" in f.calls.scene[0]));
  });
  it("pen, eraser and hand hide the card", () => {
    for (const t of ["freedraw", "eraser", "hand"]) {
      const store = createPropsStore(fake({ activeTool: { type: t } }).api, mkEnv() as never);
      assert.equal(store.get().source, null);
    }
  });
});

describe("selection source", () => {
  const scene = () => [
    el("f1", "freedraw", { points: [[0, 0], [1, 1]], pressures: [0.5, 0.6], simulatePressure: false }),
    el("f2", "freedraw", { points: [[0, 0], [2, 2]], simulatePressure: true }),
    el("gone", "rectangle", { isDeleted: true }),
    el("other", "rectangle"),
  ];
  it("edits copies of the selected elements as one undo step and leaves the pen colour alone", () => {
    const sc = scene();
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { f1: true, f2: true } }, sc);
    const store = createPropsStore(f.api, mkEnv() as never);
    assert.deepEqual(store.get().controls, ["stroke", "width", "opacity"]);
    store.set("stroke", "#2f55b8");
    assert.equal(f.calls.scene.length, 1);
    const call = f.calls.scene[0] as { elements: Rec[]; captureUpdate: unknown; appState?: unknown };
    assert.equal(call.captureUpdate, NOW);
    assert.ok(!("appState" in call));
    assert.equal(call.elements.length, sc.length);
    assert.ok(call.elements.some((e) => e.isDeleted));
    assert.equal(call.elements[3], sc[3]);
    const f1 = call.elements[0];
    assert.equal(f1.strokeColor, "#2f55b8");
    assert.deepEqual(f1.pressures, [0.5, 0.6]);
    assert.equal(f1.simulatePressure, false);
    assert.equal(f1.version, 6);
    assert.equal(call.elements[1].version, 6);
  });
  it("shows mixed values and shared values", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true, b: true } },
      [el("a", "rectangle"), el("b", "rectangle", { strokeColor: "#FF0000" })]);
    const store = createPropsStore(f.api, mkEnv() as never);
    assert.equal(store.get().values.stroke, "mixed");
    assert.equal(store.get().values.width, 2);
    assert.equal(store.get().layers, true);
    assert.equal(store.get().title, "2 selected");
  });
  it("hides for a selection holding a draft and shows again for a normal one", () => {
    const sc = [el("d", "rectangle", { customData: { draft: true } }), el("n", "rectangle")];
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { d: true, n: true } }, sc);
    const store = createPropsStore(f.api, mkEnv() as never);
    assert.equal(store.get().source, null);
    f.set({ selectedElementIds: { n: true } });
    assert.equal(store.get().source, "selection");
  });
  it("while editing text, edits go to the defaults only", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true }, editingTextElement: { id: "a" } },
      [el("a", "text", { text: "x", fontSize: 20, fontFamily: 5, lineHeight: 1.25 })]);
    const store = createPropsStore(f.api, mkEnv() as never);
    store.set("stroke", "#2f55b8");
    assert.deepEqual(f.calls.scene, [{ appState: { currentItemStrokeColor: "#2f55b8" }, captureUpdate: NEVER }]);
  });
});

describe("gestures and stability", () => {
  it("a tap-select appears only when the finger lifts", () => {
    const f = fake({ activeTool: { type: "selection" } }, [el("a", "rectangle")]);
    const store = createPropsStore(f.api, mkEnv() as never);
    let runs = 0;
    store.subscribe(() => runs++);
    f.set({ selectedElementIds: { a: true }, cursorButton: "down" });
    assert.equal(store.get().source, null);
    assert.equal(runs, 0);
    f.set({ cursorButton: "up" });
    assert.equal(store.get().source, "selection");
    assert.equal(runs, 1);
  });
  it("is cheap on every change", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, [el("a", "rectangle")]);
    const store = createPropsStore(f.api, mkEnv() as never);
    const first = store.get();
    let runs = 0;
    store.subscribe(() => runs++);
    f.calls.read = 0;
    for (let i = 0; i < 1000; i++) f.set({ cursorButton: "down", newElement: { id: "x" }, scrollX: i });
    assert.equal(f.calls.read, 0);
    assert.equal(runs, 0);
    f.set({ cursorButton: "up", newElement: null });
    assert.equal(runs, 0); // same elements, same key: nothing shown changed
    assert.equal(store.get(), first);
    assert.equal(store.get(), store.get());
    const reads = f.calls.read;
    f.set({ scrollX: 5 });
    assert.equal(f.calls.read, reads);
    assert.equal(runs, 0);
  });
  it("does not scan the scene for strokes drawn with the pen", () => {
    const f = fake({ activeTool: { type: "freedraw" } }, [el("a", "freedraw")]);
    createPropsStore(f.api, mkEnv() as never);
    f.calls.read = 0;
    for (let i = 0; i < 50; i++) f.set({}, [el("a", "freedraw"), el("b" + i, "freedraw")]);
    assert.equal(f.calls.read, 0);
  });
  it("collapse flips and notifies, controls unchanged", () => {
    const f = fake({ activeTool: { type: "ellipse" } });
    const store = createPropsStore(f.api, mkEnv() as never);
    const before = store.get().controls;
    let runs = 0;
    store.subscribe(() => runs++);
    store.toggleCollapsed();
    assert.equal(store.get().collapsed, true);
    assert.equal(runs, 1);
    assert.deepEqual(store.get().controls, before);
    store.toggleCollapsed();
    assert.equal(store.get().collapsed, false);
  });
  it("unsubscribes on dispose", () => {
    const f = fake();
    const store = createPropsStore(f.api, mkEnv() as never);
    assert.equal(f.subs.size, 1);
    store.dispose();
    assert.equal(f.subs.size, 0);
  });
});

describe("text controls", () => {
  const text = (extra: Rec = {}) => el("t", "text", { text: "hello", fontSize: 20, fontFamily: 5, lineHeight: 1.25, width: 50, height: 25, x: 100, y: 100, textAlign: "left", ...extra });
  const sel = (sc: Rec[], more: Rec = {}) => fake({ activeTool: { type: "selection" }, selectedElementIds: { t: true }, ...more }, sc);

  it("resizes the box about its centre when the size changes", () => {
    const f = sel([text()]);
    const store = createPropsStore(f.api, mkEnv(f) as never);
    assert.deepEqual(store.get().controls, ["stroke", "opacity", "fontFamily", "fontSize", "textAlign"]);
    store.set("fontSize", 36);
    const out = (f.calls.scene[0].elements as Rec[])[0];
    assert.equal(out.fontSize, 36);
    assert.deepEqual([out.width, out.height, out.x, out.y], [90, 45, 80, 90]);
    assert.equal(out.version, 6);
    assert.equal(f.calls.scene[0].captureUpdate, NOW);
  });
  it("loads the font before it measures and writes", async () => {
    const f = sel([text()]);
    const store = createPropsStore(f.api, mkEnv(f) as never);
    loads.length = 0;
    await store.set("fontFamily", 6);
    assert.deepEqual(loads, [[6, 20]]);
    assert.deepEqual(f.calls.order, ["load", "update"]);
    const out = (f.calls.scene[0].elements as Rec[])[0];
    assert.equal(out.fontFamily, 6);
    assert.equal(out.width, 5 * 20 * 0.5);
  });
  it("bound text keeps its box", () => {
    const f = sel([text({ containerId: "c1" })]);
    const store = createPropsStore(f.api, mkEnv(f) as never);
    store.set("fontSize", 36);
    const out = (f.calls.scene[0].elements as Rec[])[0];
    assert.equal(out.fontSize, 36);
    assert.deepEqual([out.x, out.y, out.width, out.height], [100, 100, 50, 25]);
  });
  it("alignment touches no geometry", () => {
    const f = sel([text()]);
    const store = createPropsStore(f.api, mkEnv(f) as never);
    store.set("textAlign", "center");
    const out = (f.calls.scene[0].elements as Rec[])[0];
    assert.equal(out.textAlign, "center");
    assert.deepEqual([out.x, out.y, out.width, out.height], [100, 100, 50, 25]);
  });
  it("a text tool with nothing selected edits the defaults", async () => {
    const f = fake({ activeTool: { type: "text" } });
    const store = createPropsStore(f.api, mkEnv(f) as never);
    await store.set("fontSize", 28);
    assert.deepEqual(f.calls.scene, [{ appState: { currentItemFontSize: 28 }, captureUpdate: NEVER }]);
  });
});

describe("layers, duplicate, delete, lock", () => {
  const two = () => [el("a", "rectangle"), el("b", "rectangle"), el("x", "rectangle", { locked: true })];
  it("dispatch the action shortcuts and never edit the scene", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, two());
    const store = createPropsStore(f.api, mkEnv(f) as never);
    assert.equal(store.get().layers, true);
    keys.length = 0;
    store.layer("front");
    store.layer("back");
    store.layer("backward");
    store.layer("forward");
    store.duplicate();
    store.remove();
    assert.equal(keys.length, 6);
    assert.equal(keys[0].shiftKey, true);
    assert.equal(keys[0].code, "BracketRight");
    assert.equal(keys[5].key, "Delete");
    assert.equal(f.calls.scene.length, 0);
    assert.equal(createPropsStore(fake({ activeTool: { type: "rectangle" } }).api, mkEnv() as never).get().layers, false);
  });
  it("lock clears the selection in the same update", () => {
    const sc = two();
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, sc);
    const store = createPropsStore(f.api, mkEnv(f) as never);
    store.lock();
    assert.equal(f.calls.scene.length, 1);
    const call = f.calls.scene[0] as { elements: Rec[]; appState: Rec; captureUpdate: unknown };
    assert.equal(call.elements[0].locked, true);
    assert.equal(call.elements[0].version, 6);
    assert.equal(call.elements[1], sc[1]);
    assert.deepEqual(call.appState, { selectedElementIds: {} });
    assert.equal(call.captureUpdate, NOW);
  });
  it("unlock all frees every locked element and is a no-op otherwise", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, two());
    const store = createPropsStore(f.api, mkEnv(f) as never);
    assert.equal(store.get().anyLocked, true);
    store.unlockAll();
    const out = (f.calls.scene[0].elements as Rec[]);
    assert.equal(out[2].locked, false);
    assert.equal(out[2].version, 6);
    const g = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, [el("a", "rectangle")]);
    const s2 = createPropsStore(g.api, mkEnv(g) as never);
    assert.equal(s2.get().anyLocked, false);
    s2.unlockAll();
    assert.equal(g.calls.scene.length, 0);
  });
  it("anyLocked is not recomputed on pointer moves", () => {
    const f = fake({ activeTool: { type: "selection" }, selectedElementIds: { a: true } }, two());
    createPropsStore(f.api, mkEnv(f) as never);
    f.calls.read = 0;
    for (let i = 0; i < 100; i++) f.set({ scrollX: i, cursorButton: "down" });
    assert.equal(f.calls.read, 0);
  });
});
