import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  markDraft,
  opFontSize,
  wrapText,
  prefixIds,
  measureDrafts,
  type DraftElement,
  type PendingOp,
} from "../src/drafts/drafts.ts";

const op: PendingOp = {
  op_id: "op1",
  op_type: "draw_diagram",
  payload: { mermaid: "flowchart TD\nA-->B", id_prefix: "op1:" },
};

// What convertToExcalidrawElements gives for "A --> B": two boxes with bound labels and an arrow.
const converted = (): DraftElement[] => [
  { id: "r1", type: "rectangle", x: 10, y: 20, width: 100, height: 40, boundElements: [{ id: "t1", type: "text" }, { id: "a1", type: "arrow" }] },
  { id: "t1", type: "text", x: 20, y: 30, width: 10, height: 20, containerId: "r1", text: "A" },
  { id: "r2", type: "rectangle", x: 10, y: 120, width: 100, height: 40, boundElements: [{ id: "a1", type: "arrow" }] },
  {
    id: "a1", type: "arrow", x: 60, y: 60, width: 0, height: 60, points: [[0, 0], [0, 60]],
    startBinding: { elementId: "r1", focus: 0, gap: 1 }, endBinding: { elementId: "r2", focus: 0, gap: 1 },
  },
];

describe("drafts", () => {
  it("gives every element a prefixed id and rewrites every reference", () => {
    const out = prefixIds(converted(), "op1:");
    assert.deepEqual(out.map((e) => e.id), ["op1:1", "op1:2", "op1:3", "op1:4"]);
    assert.deepEqual(out[0].boundElements, [{ id: "op1:2", type: "text" }, { id: "op1:4", type: "arrow" }]);
    assert.equal(out[1].containerId, "op1:1");
    assert.equal(out[3].startBinding?.elementId, "op1:1");
    assert.equal(out[3].endBinding?.elementId, "op1:3");
    assert.equal(out[3].startBinding?.gap, 1);
  });

  it("gives groups op-scoped ids, shared within the op", () => {
    const out = prefixIds(
      [
        { id: "a", x: 0, y: 0, groupIds: ["g", "h"] },
        { id: "b", x: 0, y: 0, groupIds: ["g"] },
      ],
      "op1:",
    );
    assert.deepEqual(out[0].groupIds, ["op1:g1", "op1:g2"]);
    assert.deepEqual(out[1].groupIds, ["op1:g1"]);
  });

  it("drops references to anything outside the op (never points at user ink)", () => {
    const out = prefixIds(
      [
        { id: "t", type: "text", x: 0, y: 0, containerId: "user-box" },
        { id: "a", type: "arrow", x: 0, y: 0, startBinding: { elementId: "user-box" }, endBinding: null, boundElements: [{ id: "user-x", type: "arrow" }] },
      ],
      "p:",
    );
    assert.equal(out[0].containerId, null);
    assert.equal(out[1].startBinding, null);
    assert.deepEqual(out[1].boundElements, []);
  });

  it("tags drafts and draws them dashed, keeping other customData", () => {
    const [e] = markDraft([{ id: "a", type: "rectangle", x: 0, y: 0, customData: { keep: 1 } }], "op1");
    assert.equal(e.strokeStyle, "dashed");
    assert.deepEqual(e.customData, { keep: 1, author: "agent", draft: true, op_id: "op1" });
  });

  it("measures the converted elements: prefixed ids and their bbox, input untouched", () => {
    const input = converted();
    const before = JSON.stringify(input);
    const m = measureDrafts(input, op);
    assert.equal(JSON.stringify(input), before);
    assert.ok(m.elements.every((e) => e.id.startsWith("op1:")));
    assert.deepEqual([m.width, m.height], [100, 140]);
  });
});

describe("opFontSize", () => {
  it("uses the server value, clamped, else 20", () => {
    assert.equal(opFontSize({ font_size: 36 }), 36);
    assert.equal(opFontSize({}), 20);
    assert.equal(opFontSize({ font_size: 5000 }), 2000);
    assert.equal(opFontSize({ font_size: 450 }), 450);
    assert.equal(opFontSize({ font_size: -3 }), 20);
  });
});

describe("wrapText", () => {
  it("breaks at spaces within maxChars and keeps newlines", () => {
    const text = Array.from({ length: 30 }, () => "word").join(" ");
    assert.ok(wrapText(text, 50).split("\n").every((l) => l.length <= 50));
    assert.equal(wrapText("a b\nc d", 50), "a b\nc d");
  });
  it("hard-breaks long words and ignores a missing width", () => {
    assert.deepEqual(wrapText("x".repeat(70), 50).split("\n").map((l) => l.length), [50, 20]);
    assert.equal(wrapText("x".repeat(70), undefined), "x".repeat(70));
    assert.equal(wrapText("x".repeat(70), 0), "x".repeat(70));
  });
});
