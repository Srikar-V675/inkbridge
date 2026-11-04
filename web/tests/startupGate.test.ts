import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createStartupGate } from "../src/startupGate.ts";

const sync = (f: () => void) => f();

describe("startup gate (INK-080)", () => {
  it("holds work until open, then runs it once", () => {
    const gate = createStartupGate(sync);
    let n = 0;
    gate.whenReady(() => n++);
    assert.equal(n, 0);
    gate.open();
    assert.equal(n, 1);
    gate.open();
    assert.equal(n, 1);
  });
  it("cancel prevents the call", () => {
    const gate = createStartupGate(sync);
    let n = 0;
    gate.whenReady(() => n++)();
    gate.open();
    assert.equal(n, 0);
  });
  it("work queued after open still runs", () => {
    const gate = createStartupGate(sync);
    gate.open();
    let n = 0;
    gate.whenReady(() => n++);
    assert.equal(n, 1);
  });
});
