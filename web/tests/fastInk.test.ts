import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { canDraw, deviceBox, FREEDRAW, inputPoints, installFastInk, strokeOptions, tracePath, type FreedrawLike } from "../src/ink/fastInk.ts";
import { createPenSamples } from "../src/ink/penSamples.ts";

const el = (over: Partial<FreedrawLike> = {}): FreedrawLike => ({
  id: "a", type: "freedraw", x: 100, y: 50, angle: 0, opacity: 100, strokeColor: "black", strokeWidth: 2,
  simulatePressure: false, points: [[0, 0], [1, 1]], pressures: [0.4, 0.5], ...over,
});
const view = { scrollX: 10, scrollY: 20, zoom: 2, offsetLeft: 4, offsetTop: 6 };

describe("strokeOptions", () => {
  it("matches the patched Excalidraw freedraw options", () => {
    const src = readFileSync(new URL("../node_modules/@excalidraw/excalidraw/dist/dev/chunk-4FTI6OG3.js", import.meta.url), "utf8");
    const body = src.slice(src.indexOf("function getFreeDrawSvgPath"), src.indexOf("function med("));
    assert.ok(body.includes(`size: element.strokeWidth * ${FREEDRAW.sizePerWidth},`));
    assert.ok(body.includes(`thinning: ${FREEDRAW.thinning},`));
    assert.ok(body.includes(`smoothing: ${FREEDRAW.smoothing},`));
    assert.ok(body.includes(`streamline: ${FREEDRAW.streamline},`));
    assert.ok(body.includes("easing: (t) => Math.sin(t * Math.PI / 2)"));
    const o = strokeOptions(el({ strokeWidth: 4 }));
    assert.equal(o.size, 17);
    assert.equal(o.last, false);
    assert.equal(o.easing(1), 1);
  });
});

describe("canDraw", () => {
  it("takes only an opaque, unrotated stroke still in progress", () => {
    assert.equal(canDraw(el()), true);
    assert.equal(canDraw(el({ opacity: 35 })), false); // highlighter
    assert.equal(canDraw(el({ angle: 0.1 })), false);
    assert.equal(canDraw(el({ lastCommittedPoint: [1, 1] })), false);
    assert.equal(canDraw(el({ type: "line" })), false);
    assert.equal(canDraw(null), false);
  });
});

describe("inputPoints", () => {
  it("appends pending samples in element coordinates, skips repeats, keeps pressures", () => {
    // client = offset + (element.x + dx + scrollX) * zoom: element point (3, 2) is client (4 + 113 * 2, 6 + 72 * 2)
    const s = (dx: number, dy: number, p: number) => ({ clientX: 4 + (100 + dx + 10) * 2, clientY: 6 + (50 + dy + 20) * 2, pressure: p });
    const got = inputPoints(el(), [s(3, 2, 0.7), s(3, 2, 0.9), s(4, 2, 0.8)], view);
    assert.deepEqual(got, [[0, 0, 0.4], [1, 1, 0.5], [3, 2, 0.7], [4, 2, 0.8]]);
  });
  it("drops pressure for a simulated-pressure stroke, as Excalidraw does", () => {
    assert.deepEqual(inputPoints(el({ simulatePressure: true, pressures: [] }), [], view), [[0, 0], [1, 1]]);
  });
});

describe("deviceBox", () => {
  it("bounds the outline in device pixels with a 2 px margin", () => {
    assert.deepEqual(deviceBox([[0, 0], [10, 5], [-2, 3]], 2, 100, 50), [94, 48, 122, 62]);
    assert.deepEqual(deviceBox([], 2, 0, 0), [0, 0, 0, 0]);
  });
});

describe("tracePath", () => {
  it("follows Excalidraw's getSvgPathFromStroke: M p0, Q through midpoints, L p0, Z", () => {
    const calls: string[] = [];
    const ctx = {
      beginPath: () => calls.push("B"),
      moveTo: (x: number, y: number) => calls.push(`M${x},${y}`),
      quadraticCurveTo: (a: number, b: number, x: number, y: number) => calls.push(`Q${a},${b} ${x},${y}`),
      lineTo: (x: number, y: number) => calls.push(`L${x},${y}`),
      closePath: () => calls.push("Z"),
    };
    tracePath(ctx, [[0, 0], [2, 0], [2, 2]]);
    assert.deepEqual(calls, ["B", "M0,0", "Q0,0 1,0", "Q2,0 2,1", "Q2,2 1,1", "L0,0", "Z"]);
  });
});

function harness(over: { newElement?: FreedrawLike | null } = {}) {
  const handlers = new Map<string, (e: PointerEvent) => void>();
  const frames: Array<() => void> = [];
  const log: string[] = [];
  const samples = createPenSamples();
  let state = { newElement: over.newElement === undefined ? el() : over.newElement, view, width: 800, height: 600 };
  const ctx = {
    canvas: { width: 1600, height: 1200 },
    setTransform: (...a: number[]) => log.push(`T${a.join(",")}`),
    clearRect: () => log.push("clear"),
    beginPath() {}, moveTo() {}, quadraticCurveTo() {}, lineTo() {}, closePath() {},
    fill: () => log.push("fill"),
    fillStyle: "",
  };
  const off = installFastInk({
    win: { addEventListener: (t, cb) => void handlers.set(t, cb), removeEventListener: (t) => void handlers.delete(t) },
    samples,
    state: () => state,
    mayDraw: (t) => t === "pen" || t === "mouse",
    isCanvas: (t) => t === "canvas",
    surface: { prepare: () => ctx as never, clear: () => log.push("surface.clear") },
    dpr: () => 2,
    frame: (cb) => void frames.push(cb),
  });
  const fire = (t: string, e: Partial<PointerEvent>) => handlers.get(t)?.({ pointerId: 1, pointerType: "pen", target: "canvas", ...e } as PointerEvent);
  return { fire, frames, log, setState: (s: Partial<typeof state>) => (state = { ...state, ...s }), off, handlers, samples };
}

describe("installFastInk", () => {
  it("draws on each move of the stroke's pointer at the element's screen position", () => {
    const h = harness();
    h.fire("pointerdown", {});
    h.fire("pointermove", {});
    // dpr 2 x zoom 2 = 4; origin (100 + 10) * 4, (50 + 20) * 4
    assert.deepEqual(h.log, ["T1,0,0,1,0,0", "clear", "T4,0,0,4,440,280", "fill"]);
    h.fire("pointermove", { pointerId: 2 }); // a palm
    assert.equal(h.log.filter((l) => l === "fill").length, 1);
  });

  it("ignores a finger, a down off the canvas and a stroke it cannot match", () => {
    const h = harness();
    h.fire("pointerdown", { pointerType: "touch" });
    h.fire("pointermove", { pointerType: "touch" });
    h.fire("pointerdown", { target: "toolbar" as never });
    h.fire("pointermove", {});
    assert.deepEqual(h.log, []);
    const hl = harness({ newElement: el({ opacity: 35 }) });
    hl.fire("pointerdown", {});
    hl.fire("pointermove", {});
    assert.deepEqual(hl.log, []);
  });

  it("clears only after Excalidraw has finished the stroke and drawn it", () => {
    const h = harness();
    h.fire("pointerdown", {});
    h.fire("pointermove", {});
    h.fire("pointerup", {});
    h.frames.shift()!(); // newElement still set: keep waiting
    assert.ok(!h.log.includes("surface.clear"));
    h.setState({ newElement: null });
    while (h.frames.length) h.frames.shift()!();
    assert.equal(h.log.filter((l) => l === "surface.clear").length, 1);
  });

  it("a new stroke cancels the pending clear of the last one", () => {
    const h = harness();
    h.fire("pointerdown", {});
    h.fire("pointermove", {});
    h.fire("pointerup", {});
    h.fire("pointerdown", {});
    h.setState({ newElement: null });
    while (h.frames.length) h.frames.shift()!();
    assert.ok(!h.log.includes("surface.clear"));
  });

  it("removes its listeners and clears on uninstall", () => {
    const h = harness();
    h.fire("pointerdown", {});
    h.fire("pointermove", {});
    h.off();
    assert.equal(h.handlers.size, 0);
    assert.ok(h.log.includes("surface.clear"));
  });
});
