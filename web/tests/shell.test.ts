import assert from "node:assert/strict";
import { describe, it } from "node:test";
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
