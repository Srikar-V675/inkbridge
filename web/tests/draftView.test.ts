import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  BATCH_MS,
  createUnseen,
  draftBox,
  hasFlowArrow,
  isFlowArrow,
  inView,
  MARGIN_PX,
  panTarget,
  planReveal,
  viewportBox,
  type Viewport,
} from "../src/drafts/draftView.ts";

const draft = (opId: string) => ({ customData: { author: "agent", draft: true, op_id: opId } });

describe("draftBox", () => {
  it("bounds a text element by its x, y, width and height", () => {
    const els = [{ id: "a:1", x: 10, y: 20, width: 30, height: 40, ...draft("op1") }];
    assert.deepEqual(draftBox(els, "op1"), { x: 10, y: 20, width: 30, height: 40 });
  });

  it("uses the point extent (negative offsets included) for freedraw and arrows", () => {
    const els = [
      { id: "a:1", x: 100, y: 100, points: [[0, 0], [-20, 5], [15, -10]], ...draft("op1") },
    ];
    assert.deepEqual(draftBox(els, "op1"), { x: 80, y: 90, width: 35, height: 15 });
  });

  it("unions several elements of one op", () => {
    const els = [
      { id: "a:1", x: 0, y: 0, width: 10, height: 10, ...draft("op1") },
      { id: "a:2", x: 50, y: 60, width: 10, height: 10, ...draft("op1") },
    ];
    assert.deepEqual(draftBox(els, "op1"), { x: 0, y: 0, width: 60, height: 70 });
  });

  it("ignores deleted elements, other ops and elements without the op tag", () => {
    const els = [
      { id: "a:1", x: 0, y: 0, width: 10, height: 10, isDeleted: true, ...draft("op1") },
      { id: "a:2", x: 500, y: 500, width: 10, height: 10, ...draft("op2") },
      { id: "user:1", x: 900, y: 900, width: 10, height: 10, customData: {} },
    ];
    assert.equal(draftBox(els, "op1"), null);
    assert.deepEqual(draftBox(els, "op2"), { x: 500, y: 500, width: 10, height: 10 });
  });

  it("matches customData.op_id, not the element id prefix", () => {
    const els = [{ id: "op1:1", x: 0, y: 0, width: 10, height: 10, ...draft("other") }];
    assert.equal(draftBox(els, "op1"), null);
  });

  it("returns null when the op has no live draft element", () => {
    assert.equal(draftBox([], "op1"), null);
  });
});

describe("inView", () => {
  // Viewport 1000x800 screen px at zoom 10 shows 100x80 scene units at scroll 0.
  const zoomed: Viewport = { scrollX: 0, scrollY: 0, zoom: 10, width: 1000, height: 800 };
  const normal: Viewport = { ...zoomed, zoom: 1 };
  const box = (x: number, y = 0, width = 20, height = 20) => ({ x, y, width, height });

  it("uses the current zoom: a box at x=500 is off-screen at 10x and on-screen at 1x", () => {
    assert.equal(inView(box(500), zoomed), false);
    assert.equal(inView(box(500), normal), true);
  });

  it("needs at least half of the box inside the viewport", () => {
    // viewport x 0..100; box 90..110 has half inside
    assert.equal(inView(box(90), zoomed), true);
    // box 96..116 has 20% inside
    assert.equal(inView(box(96), zoomed), false);
  });

  it("accepts a box larger than the viewport that covers it", () => {
    assert.equal(inView(box(-500, -500, 2000, 2000), zoomed), true);
  });

  it("follows the scroll: scrollX=-500 at 1x shows x 500..1500", () => {
    const scrolled: Viewport = { ...normal, scrollX: -500 };
    assert.equal(inView(box(600, 0, 10, 10), scrolled), true);
    assert.equal(inView(box(0, 0, 10, 10), scrolled), false);
  });

  it("viewportBox converts screen size to scene units", () => {
    assert.deepEqual(viewportBox({ ...zoomed, scrollX: -30, scrollY: -5 }), {
      x: 30,
      y: 5,
      width: 100,
      height: 80,
    });
  });
});

describe("panTarget", () => {
  const v: Viewport = { scrollX: 0, scrollY: 0, zoom: 1, width: 1000, height: 800 };

  it("centres a small box and keeps the zoom (applied, then in view)", () => {
    const small = { x: 3000, y: 2000, width: 20, height: 20 };
    const t = panTarget(small, v);
    const after = { ...v, scrollX: t.scrollX, scrollY: t.scrollY };
    assert.equal(inView(small, after), true);
    assert.equal(-t.scrollX + 500, 3010); // viewport centre lands on the box centre
    assert.equal(-t.scrollY + 400, 2010);
  });

  it("centres at 10x too, in scene units", () => {
    const zoomed: Viewport = { ...v, zoom: 10 };
    const small = { x: 500, y: 40, width: 20, height: 20 };
    const t = panTarget(small, zoomed);
    const after = { ...zoomed, scrollX: t.scrollX, scrollY: t.scrollY };
    assert.equal(inView(small, after), true);
    assert.equal(-t.scrollX + 50, 510);
  });

  it("aligns a box wider than the viewport to a margin at its top-left", () => {
    // 300 scene units wide at 10x (view is 100 wide): X uses the margin; 10 tall fits, so Y centres.
    const wide = { x: 0, y: 0, width: 300, height: 10 };
    const zoomed: Viewport = { ...v, zoom: 10 };
    const t = panTarget(wide, zoomed);
    const m = MARGIN_PX / 10;
    assert.equal(t.scrollX, -(0 - m));
    assert.equal(t.scrollY, -(0 + 5 - 80 / 2));
  });
});

describe("planReveal", () => {
  const v: Viewport = { scrollX: 0, scrollY: 0, zoom: 1, width: 1000, height: 800 };
  const inside = { x: 10, y: 10, width: 20, height: 20 };
  const outside = { x: 5000, y: 10, width: 20, height: 20 };
  const now = 100_000;

  it("does nothing when the draft is in view, even with the pen down", () => {
    assert.equal(planReveal({ box: inside, view: v, penDown: true, lastPanAt: null, now }), "none");
    assert.equal(planReveal({ box: inside, view: v, penDown: false, lastPanAt: null, now }), "none");
  });

  it("offers a chip, not a pan, while the pen is down", () => {
    assert.equal(planReveal({ box: outside, view: v, penDown: true, lastPanAt: null, now }), "chip");
  });

  it("offers a chip when a pan happened less than a batch window ago", () => {
    assert.equal(planReveal({ box: outside, view: v, penDown: false, lastPanAt: now - 1000, now }), "chip");
    assert.ok(BATCH_MS > 1000);
  });

  it("pans when the last pan was long ago or never happened", () => {
    assert.equal(planReveal({ box: outside, view: v, penDown: false, lastPanAt: now - 2000, now }), "pan");
    assert.equal(planReveal({ box: outside, view: v, penDown: false, lastPanAt: null, now }), "pan");
  });
});

describe("createUnseen", () => {
  it("add is idempotent and keeps insertion order", () => {
    const u = createUnseen();
    u.add("b");
    u.add("a");
    u.add("b");
    assert.deepEqual([...u.ids()], ["b", "a"]);
  });

  it("remove drops one id", () => {
    const u = createUnseen();
    u.add("a");
    u.add("b");
    u.remove("a");
    assert.deepEqual([...u.ids()], ["b"]);
  });

  it("prune keeps only live ids", () => {
    const u = createUnseen();
    u.add("a");
    u.add("b");
    u.add("c");
    u.prune(new Set(["c", "a"]));
    assert.deepEqual([...u.ids()], ["a", "c"]);
  });

  it("subscribe fires only when the set changes", () => {
    const u = createUnseen();
    let calls = 0;
    const off = u.subscribe(() => calls++);
    u.add("a");
    u.add("a");
    u.remove("zzz");
    u.prune(new Set(["a"]));
    assert.equal(calls, 1);
    u.remove("a");
    assert.equal(calls, 2);
    off();
    u.add("b");
    assert.equal(calls, 2);
  });

  it("ids() keeps its reference until the content changes", () => {
    const u = createUnseen();
    u.add("a");
    const first = u.ids();
    u.add("a");
    u.remove("zzz");
    u.prune(new Set(["a"]));
    assert.equal(u.ids(), first);
    u.add("b");
    assert.notEqual(u.ids(), first);
  });
});

describe("flow arrow", () => {
  const arrow = (extra: Record<string, unknown> = {}) => ({
    id: "a:flow-arrow",
    customData: { op_id: "a" },
    ...extra,
  });
  it("is found by id and op, ignoring deleted or other ops", () => {
    assert.equal(isFlowArrow({ id: "a:flow-arrow" }), true);
    assert.equal(isFlowArrow({ id: "a:1" }), false);
    assert.equal(hasFlowArrow([arrow()], "a"), true);
    assert.equal(hasFlowArrow([arrow({ isDeleted: true })], "a"), false);
    assert.equal(hasFlowArrow([arrow()], "b"), false);
    assert.equal(hasFlowArrow([{ id: "a:1", customData: { op_id: "a" } }], "a"), false);
  });
});
