import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { installTouchInput, whenLoaded, type PtrEvent, type TouchDeps } from "../src/app/touchInput.ts";
import { ZOOM_MAX } from "../src/app/shellLogic.ts";

type Ev = Partial<PtrEvent> & { type: string; pointerType: string };

function setup(opts: { tool?: string; fingerDraws?: boolean; elements?: { x: number; y: number; width: number; height: number }[] } = {}) {
  const listeners = new Map<string, Set<(e: PtrEvent) => void>>();
  const view = { scrollX: 0, scrollY: 0, zoom: 2, offsetLeft: 0, offsetTop: 0 };
  const state = { tool: opts.tool ?? "freedraw", fingerDraws: opts.fingerDraws ?? false, t: 0, setViewCalls: 0 };
  const win = {
    addEventListener(t: string, cb: (e: PtrEvent) => void) { (listeners.get(t) ?? listeners.set(t, new Set()).get(t)!).add(cb); },
    removeEventListener(t: string, cb: (e: PtrEvent) => void) { listeners.get(t)?.delete(cb); },
  };
  const deps: TouchDeps = {
    win,
    isCanvas: (t) => t === "canvas",
    tool: () => state.tool,
    view: () => ({ ...view }),
    setView: (v) => { state.setViewCalls++; view.scrollX = v.scrollX; view.scrollY = v.scrollY; view.zoom = v.zoom; },
    elements: () => opts.elements ?? [],
    fingerDraws: () => state.fingerDraws,
    now: () => state.t,
    schedule: (cb) => { cb(); return () => {}; },
  };
  const dispose = installTouchInput(deps);
  const stopped: string[] = [];
  const fire = (e: Ev) => {
    let stop = false;
    const ev: PtrEvent = { pointerId: 1, clientX: 0, clientY: 0, target: "canvas", ...e, stopPropagation: () => { stop = true; } };
    for (const cb of [...(listeners.get(e.type) ?? [])]) cb(ev);
    if (stop) stopped.push(`${e.type}:${e.pointerType}:${ev.pointerId}`);
    return stop;
  };
  const count = () => [...listeners.values()].reduce((n, s) => n + s.size, 0);
  return { fire, view, state, stopped, dispose, count };
}

describe("installTouchInput", () => {
  for (const tool of ["freedraw", "eraser", "rectangle"]) {
    it(`a finger drag pans on ${tool} and Excalidraw never sees it`, () => {
      const s = setup({ tool });
      assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", clientX: 100, clientY: 100 }), true);
      assert.equal(s.fire({ type: "pointermove", pointerType: "touch", clientX: 200, clientY: 100 }), true);
      assert.equal(s.fire({ type: "pointerup", pointerType: "touch", clientX: 200, clientY: 100 }), true);
      assert.equal(s.view.scrollX, 50);
      assert.equal(s.view.scrollY, 0);
      assert.equal(s.view.zoom, 2);
    });
  }

  it("never stops or moves for the pen or the mouse", () => {
    const s = setup();
    for (const pointerType of ["pen", "mouse"]) {
      for (const type of ["pointerdown", "pointermove", "pointerup"]) {
        assert.equal(s.fire({ type, pointerType, clientX: 50, clientY: 50, pressure: 0.5 } as Ev), false);
      }
    }
    assert.equal(s.state.setViewCalls, 0);
  });

  it("leaves touches outside the canvas alone", () => {
    const s = setup();
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", target: "rail-button" }), false);
    assert.equal(s.fire({ type: "pointermove", pointerType: "touch", clientX: 90 }), false);
    assert.equal(s.fire({ type: "pointerup", pointerType: "touch" }), false);
    assert.equal(s.state.setViewCalls, 0);
  });

  it("passes the finger to Excalidraw when Finger draws is on", () => {
    const s = setup({ fingerDraws: true });
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", clientX: 100 }), false);
    assert.equal(s.fire({ type: "pointermove", pointerType: "touch", clientX: 200 }), false);
    assert.equal(s.fire({ type: "pointerup", pointerType: "touch" }), false);
    assert.equal(s.state.setViewCalls, 0);
  });

  it("ignores a palm near the pen and pans again after the grace window", () => {
    const s = setup();
    s.fire({ type: "pointermove", pointerType: "pen" });
    s.state.t = 100;
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2, clientX: 100 }), true);
    assert.equal(s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 300 }), true);
    assert.equal(s.fire({ type: "pointerup", pointerType: "touch", pointerId: 2, clientX: 300 }), true);
    assert.equal(s.state.setViewCalls, 0);
    assert.equal(s.view.scrollX, 0);
    s.state.t = 1000;
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 3, clientX: 100 });
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 3, clientX: 200 });
    s.fire({ type: "pointerup", pointerType: "touch", pointerId: 3, clientX: 200 });
    assert.equal(s.view.scrollX, 50);
  });

  it("ignores a palm while the pen is down, however long", () => {
    const s = setup();
    s.fire({ type: "pointerdown", pointerType: "pen", pointerId: 9 });
    s.state.t = 10_000;
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2 }), true);
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 400 });
    assert.equal(s.state.setViewCalls, 0);
  });

  it("selection tool: finger on an element passes, on empty canvas pans", () => {
    const s = setup({ tool: "selection", elements: [{ x: 40, y: 40, width: 20, height: 20 }] });
    // viewport (100,100) at zoom 2 = scene (50,50): inside the element
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 1, clientX: 100, clientY: 100 }), false);
    s.fire({ type: "pointerup", pointerType: "touch", pointerId: 1 });
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2, clientX: 600, clientY: 600 }), true);
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 700, clientY: 600 });
    s.fire({ type: "pointerup", pointerType: "touch", pointerId: 2, clientX: 700, clientY: 600 });
    assert.equal(s.view.scrollX, 50);
  });

  it("text tool passes, and a second finger follows a passed first finger", () => {
    const s = setup({ tool: "text" });
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 1 }), false);
    s.state.tool = "freedraw";
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2 }), false);
    assert.equal(s.state.setViewCalls, 0);
  });

  it("pinches: spread doubling doubles zoom with the centre point held, and clamps", () => {
    const s = setup();
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 1, clientX: 100, clientY: 100 });
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2, clientX: 200, clientY: 100 });
    const sceneX = 150 / 2 - 0;
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 1, clientX: 50, clientY: 100 });
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 250, clientY: 100 });
    assert.equal(s.view.zoom, 4);
    assert.ok(Math.abs(150 / s.view.zoom - s.view.scrollX - sceneX) < 1e-9);
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 100_000, clientY: 100 });
    assert.equal(s.view.zoom, ZOOM_MAX);
  });

  it("lifting one finger of a pinch re-anchors: the other pans by exactly its move", () => {
    const s = setup();
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 1, clientX: 100, clientY: 100 });
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 2, clientX: 200, clientY: 100 });
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 300, clientY: 100 });
    s.fire({ type: "pointerup", pointerType: "touch", pointerId: 1, clientX: 100, clientY: 100 });
    const before = { ...s.view };
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 2, clientX: 340, clientY: 120 });
    assert.equal(s.view.zoom, before.zoom);
    assert.ok(Math.abs(s.view.scrollX - (before.scrollX + 40 / before.zoom)) < 1e-9);
    assert.ok(Math.abs(s.view.scrollY - (before.scrollY + 20 / before.zoom)) < 1e-9);
  });

  it("a pen landing mid-pan ends the pan", () => {
    const s = setup();
    s.fire({ type: "pointerdown", pointerType: "touch", pointerId: 1, clientX: 100 });
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 1, clientX: 140 });
    assert.equal(s.state.setViewCalls, 1);
    assert.equal(s.fire({ type: "pointerdown", pointerType: "pen", pointerId: 7 }), false);
    s.fire({ type: "pointermove", pointerType: "touch", pointerId: 1, clientX: 300 });
    assert.equal(s.state.setViewCalls, 1);
  });

  it("the disposer removes every listener", () => {
    const s = setup();
    assert.equal(s.count(), 4);
    s.dispose();
    assert.equal(s.count(), 0);
    assert.equal(s.fire({ type: "pointerdown", pointerType: "touch", clientX: 10 }), false);
    s.fire({ type: "pointermove", pointerType: "touch", clientX: 90 });
    assert.equal(s.state.setViewCalls, 0);
  });
});

describe("whenLoaded", () => {
  function frames() {
    const q: (() => void)[] = [];
    return { frame: (cb: () => void) => { q.push(cb); return () => void q.splice(q.indexOf(cb), 1); }, step: () => q.shift()?.(), size: () => q.length };
  }
  it("applies once after loading ends", () => {
    const f = frames();
    const api = { loading: true, getAppState() { return { isLoading: this.loading }; } };
    let n = 0;
    whenLoaded(api, f.frame, () => n++);
    f.step(); f.step();
    assert.equal(n, 0);
    api.loading = false;
    f.step(); f.step(); f.step();
    assert.equal(n, 1);
  });
  it("applies anyway after maxFrames", () => {
    const f = frames();
    let n = 0;
    whenLoaded({ getAppState: () => ({ isLoading: true }) }, f.frame, () => n++, 3);
    for (let i = 0; i < 10; i++) f.step();
    assert.equal(n, 1);
  });
  it("cancel before loading ends never applies", () => {
    const f = frames();
    const api = { loading: true, getAppState() { return { isLoading: this.loading }; } };
    let n = 0;
    const cancel = whenLoaded(api, f.frame, () => n++);
    f.step();
    cancel();
    api.loading = false;
    for (let i = 0; i < 5; i++) f.step();
    assert.equal(n, 0);
  });
});
