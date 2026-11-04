import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createLoadClock } from "../src/loadClock.ts";

describe("load clock (INK-080)", () => {
  it("records time since the previous mark, then the total", () => {
    const ticks = [0, 10, 30, 35];
    const got: Array<[string, number, Record<string, number>]> = [];
    const clock = createLoadClock(() => ticks.shift() as number, (n, ms, c) => got.push([n, ms, c ?? {}]));
    clock.mark("fetch");
    clock.mark("parse", { bytes: 5 });
    clock.total({ elements: 2 });
    assert.deepEqual(got, [
      ["load.fetch", 10, {}],
      ["load.parse", 20, { bytes: 5 }],
      ["load.total", 35, { elements: 2 }],
    ]);
  });
});
