import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { acceptOp, draftOps } from "../src/resolve.ts";
import { markDraft, type DraftElement } from "../src/drafts.ts";

const draftsOf = (opId: string, n: number): DraftElement[] =>
  markDraft(
    Array.from({ length: n }, (_, i) => ({
      id: `${opId}:${i + 1}`,
      type: i === 0 ? "text" : "rectangle",
      x: 0,
      y: 0,
      version: 3,
      opacity: 100,
    })),
    opId,
  );

describe("acceptOp", () => {
  it("accepts only the op's elements and leaves everything else the same object", () => {
    const user: DraftElement = { id: "u1", type: "freedraw", x: 1, y: 2, version: 1 };
    const other = draftsOf("op2", 1);
    const mine = draftsOf("op1", 2);
    const out = acceptOp([user, ...other, ...mine], "op1:");
    assert.equal(out[0], user);
    assert.equal(out[1], other[0]);
    assert.notEqual(out[2], mine[0]);
    assert.notEqual(out[3], mine[1]);
  });

  it("strips draft, keeps author and op_id, solidifies, restores text opacity, bumps version", () => {
    const [text, box] = acceptOp(draftsOf("op1", 2), "op1:");
    for (const e of [text, box]) {
      assert.equal(e.customData?.draft, undefined);
      assert.equal("draft" in (e.customData ?? {}), false);
      assert.equal(e.customData?.author, "agent");
      assert.equal(e.customData?.op_id, "op1");
      assert.equal(e.strokeStyle, "solid");
      assert.equal(e.version, 4);
    }
    assert.equal(text.opacity, 100);
  });

  it("restores a faded text to 100 but leaves other opacity", () => {
    const els = draftsOf("op1", 2);
    assert.equal(els[0].opacity, 70);
    els[1].opacity = 40;
    const out = acceptOp(els, "op1:");
    assert.equal(out[0].opacity, 100);
    assert.equal(out[1].opacity, 40);
  });

  it("does not touch deleted prefixed elements", () => {
    const gone: DraftElement = { ...draftsOf("op1", 1)[0], isDeleted: true };
    assert.equal(acceptOp([gone], "op1:")[0], gone);
  });
});

describe("draftOps", () => {
  it("lists live drafts per op in scene order", () => {
    const a = draftsOf("opA", 2);
    const b = draftsOf("opB", 1);
    const user: DraftElement = { id: "u1", type: "line", x: 0, y: 0 };
    const deleted: DraftElement = { ...draftsOf("opC", 1)[0], isDeleted: true };
    assert.deepEqual(draftOps([a[0], user, b[0], deleted, a[1]]), [
      { opId: "opA", count: 2 },
      { opId: "opB", count: 1 },
    ]);
  });

  it("ignores accepted (non-draft) elements and forged tags on user ink", () => {
    const accepted = acceptOp(draftsOf("opA", 1), "opA:");
    const forged: DraftElement = {
      id: "user9", type: "freedraw", x: 0, y: 0,
      customData: { draft: true, op_id: "opZ" },
    };
    assert.deepEqual(draftOps([...accepted, forged]), []);
  });
});
