import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  markDraft,
  opElements,
  placeAt,
  prefixIds,
  rejectOp,
  toDrafts,
  type DraftElement,
  type PendingOp,
} from "../src/drafts.ts";

const op: PendingOp = {
  op_id: "op1",
  op_type: "draw_diagram",
  payload: { mermaid: "flowchart TD\nA-->B", placement: { x: 500, y: 300 }, id_prefix: "op1:" },
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

  it("moves the group's top-left corner to the placement, arrows by their points", () => {
    const out = placeAt(
      [
        { id: "a", x: 10, y: 20, width: 5, height: 5 },
        { id: "b", x: 50, y: 50, points: [[-30, -40], [0, 0]] },
      ],
      { x: 100, y: 200 },
    );
    assert.deepEqual(out.map((e) => [e.x, e.y]), [[100, 210], [140, 240]]);
  });

  it("tags drafts and draws them dashed, keeping other customData", () => {
    const [e] = markDraft([{ id: "a", type: "rectangle", x: 0, y: 0, customData: { keep: 1 } }], "op1");
    assert.equal(e.strokeStyle, "dashed");
    assert.deepEqual(e.customData, { keep: 1, author: "agent", draft: true, op_id: "op1" });
  });

  it("runs the whole pipeline without touching the input", () => {
    const input = converted();
    const before = JSON.stringify(input);
    const out = toDrafts(input, op);
    assert.equal(JSON.stringify(input), before);
    assert.ok(out.every((e) => e.id.startsWith("op1:") && e.customData?.op_id === "op1"));
    assert.equal(Math.min(...out.map((e) => e.x)), 500);
    assert.equal(Math.min(...out.map((e) => e.y)), 300);
  });

  it("finds an op's elements so a replay is not drawn twice", () => {
    const scene = [{ id: "user", x: 0, y: 0 }, ...toDrafts(converted(), op)];
    assert.equal(opElements(scene, "op1:").length, 4);
    assert.equal(opElements(scene, "op2:").length, 0);
  });

  it("reject sweeps exactly the op's prefix and leaves user ink and other drafts alone", () => {
    const user = { id: "user", x: 0, y: 0, version: 3 };
    const other = { id: "op10:1", x: 0, y: 0, version: 1 };
    const scene = [user, other, ...toDrafts(converted(), op)];
    const out = rejectOp(scene, "op1:");
    assert.equal(out[0], user);
    assert.equal(out[1], other); // "op10:" does not start with "op1:"
    assert.ok(out.slice(2).every((e) => e.isDeleted && e.version === 1));
  });
});
