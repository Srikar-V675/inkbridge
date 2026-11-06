import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createChunkView } from "../src/chunks/chunkView.ts";

describe("chunk view store", () => {
  it("starts off and each turn-on is a new session", () => {
    const v = createChunkView();
    assert.deepEqual(v.get(), { on: false, session: 0 });
    v.toggle();
    assert.deepEqual(v.get(), { on: true, session: 1 });
    assert.equal(v.get(), v.get());
    v.toggle();
    assert.deepEqual(v.get(), { on: false, session: 1 });
    v.toggle();
    assert.deepEqual(v.get(), { on: true, session: 2 });
  });
  it("notifies subscribers once per toggle, not after unsubscribe", () => {
    const v = createChunkView();
    let n = 0;
    const off = v.subscribe(() => n++);
    v.toggle();
    assert.equal(n, 1);
    off();
    v.toggle();
    assert.equal(n, 1);
  });
});
