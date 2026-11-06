import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createGate } from "../src/lib/changeGate.ts";

describe("createGate", () => {
  it("is false the first time and true while every ref is identical", () => {
    const same = createGate();
    const els: unknown[] = [];
    const sel = {};
    assert.equal(same(els, sel), false);
    assert.equal(same(els, sel), true);
    assert.equal(same(els, sel), true);
  });
  it("is false when a ref changed, then true again for the new ones", () => {
    const same = createGate();
    const els: unknown[] = [];
    same(els, {});
    assert.equal(same(els, {}), false);
    const sel = {};
    assert.equal(same(els, sel), false);
    assert.equal(same(els, sel), true);
    assert.equal(same([], sel), false);
  });
  it("is false for a different number of refs", () => {
    const same = createGate();
    const els: unknown[] = [];
    same(els);
    assert.equal(same(els, {}), false);
  });
});
