import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  anchorFor, createPenTracker, hitsElement, penPatch, routePointer, viewFor,
  type Route, type RouteInput,
} from "../src/app/touchRouting.ts";
import { ZOOM_MAX, ZOOM_MIN } from "../src/app/shellLogic.ts";

const base: RouteInput = {
  pointerType: "touch", tool: "freedraw", penActive: false, fingerDraws: false,
  overElement: false, panning: false, touchPassed: false,
};
const row = (over: Partial<RouteInput>, expected: Route): [RouteInput, Route] => [{ ...base, ...over }, expected];

describe("routePointer", () => {
  const tools = ["freedraw", "eraser", "rectangle", "hand", "selection", "text"];
  const rows: [RouteInput, Route][] = [
    ...tools.flatMap((tool) => [
      row({ pointerType: "pen", tool }, "pass"),
      row({ pointerType: "mouse", tool }, "pass"),
      row({ tool, penActive: true }, "ignore"),
    ]),
    row({ pointerType: "pen", penActive: true }, "pass"),
    row({ fingerDraws: true }, "pass"),
    row({ touchPassed: true }, "pass"),
    row({ panning: true }, "pan"),
    row({ panning: true, tool: "text" }, "pan"),
    row({ tool: "text" }, "pass"),
    row({ tool: "selection", overElement: true }, "pass"),
    row({ tool: "selection", overElement: false }, "pan"),
    row({ tool: "freedraw" }, "pan"),
    row({ tool: "eraser" }, "pan"),
    row({ tool: "rectangle" }, "pan"),
    row({ tool: "hand" }, "pan"),
  ];
  for (const [input, expected] of rows) {
    it(`${input.pointerType} ${input.tool} ${JSON.stringify(input)} -> ${expected}`, () => {
      assert.equal(routePointer(input), expected);
    });
  }
});

describe("createPenTracker", () => {
  it("stays active while the pen is down however long", () => {
    let t = 0;
    const p = createPenTracker(() => t);
    p.observe({ type: "pointerdown", pointerType: "pen" });
    t = 10_000;
    assert.equal(p.active(), true);
    p.observe({ type: "pointerup", pointerType: "pen" });
    assert.equal(p.active(), true);
    t = 10_599;
    assert.equal(p.active(), true);
    t = 10_600;
    assert.equal(p.active(), false);
  });
  it("is inactive until a pen event, and hover keeps it active", () => {
    let t = 5000;
    const p = createPenTracker(() => t);
    assert.equal(p.active(), false);
    p.observe({ type: "pointermove", pointerType: "pen" });
    t = 5500;
    assert.equal(p.active(), true);
    t = 5700;
    assert.equal(p.active(), false);
  });
  it("pointercancel ends down, touch never activates", () => {
    let t = 0;
    const p = createPenTracker(() => t);
    p.observe({ type: "pointerdown", pointerType: "touch" });
    assert.equal(p.active(), false);
    p.observe({ type: "pointerdown", pointerType: "pen" });
    p.observe({ type: "pointercancel", pointerType: "pen" });
    t = 2000;
    assert.equal(p.active(), false);
  });
});

describe("hitsElement", () => {
  const el = { x: 100, y: 100, width: 50, height: 20 };
  it("inside, within pad, outside", () => {
    assert.equal(hitsElement([el], 120, 110, 0), true);
    assert.equal(hitsElement([el], 95, 110, 10), true);
    assert.equal(hitsElement([el], 95, 110, 2), false);
    assert.equal(hitsElement([el], 400, 400, 16), false);
    assert.equal(hitsElement([], 0, 0, 16), false);
  });
  it("ignores deleted elements", () => {
    assert.equal(hitsElement([{ ...el, isDeleted: true }], 120, 110, 0), false);
  });
  it("handles negative width and height", () => {
    const n = { x: 100, y: 100, width: -50, height: -20 };
    assert.equal(hitsElement([n], 75, 90, 0), true);
    assert.equal(hitsElement([n], 120, 110, 0), false);
  });
});

describe("pan and pinch maths", () => {
  const v = { scrollX: 10, scrollY: 20, zoom: 2 };
  it("one finger moving +dx scrolls by dx / zoom and keeps zoom", () => {
    const a = anchorFor(v, [{ x: 100, y: 100 }]);
    const n = viewFor(a, [{ x: 200, y: 130 }]);
    assert.equal(n.zoom, 2);
    assert.equal(n.scrollX, 10 + 50);
    assert.equal(n.scrollY, 20 + 15);
  });
  it("doubling the spread doubles the zoom and keeps the scene point under the centre", () => {
    const start = [{ x: 100, y: 100 }, { x: 200, y: 100 }];
    const a = anchorFor(v, start);
    const end = [{ x: 50, y: 100 }, { x: 250, y: 100 }];
    const n = viewFor(a, end);
    assert.equal(n.zoom, 4);
    const c = { x: 150, y: 100 };
    assert.ok(Math.abs(c.x / n.zoom - n.scrollX - a.scene.x) < 1e-9);
    assert.ok(Math.abs(c.y / n.zoom - n.scrollY - a.scene.y) < 1e-9);
  });
  it("clamps zoom", () => {
    const a = anchorFor(v, [{ x: 100, y: 100 }, { x: 110, y: 100 }]);
    assert.equal(viewFor(a, [{ x: 0, y: 100 }, { x: 10_000, y: 100 }]).zoom, ZOOM_MAX);
    const b = anchorFor(v, [{ x: 0, y: 100 }, { x: 1000, y: 100 }]);
    assert.equal(viewFor(b, [{ x: 500, y: 100 }, { x: 500.5, y: 100 }]).zoom, ZOOM_MIN);
  });
  it("a centre-only move with equal spread leaves zoom exactly unchanged", () => {
    const a = anchorFor({ ...v, zoom: 1.37 }, [{ x: 100, y: 100 }, { x: 160, y: 180 }]);
    const n = viewFor(a, [{ x: 130, y: 90 }, { x: 190, y: 170 }]);
    assert.equal(n.zoom, 1.37);
  });
});

describe("penPatch", () => {
  it("maps Finger draws to penMode and penDetected", () => {
    assert.deepEqual(penPatch(true), { penMode: false, penDetected: true });
    assert.deepEqual(penPatch(false), { penMode: true, penDetected: false });
  });
});
