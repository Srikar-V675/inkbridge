import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { bucketCounts, createFrameMeter, createHeartbeat } from "../src/lib/stalls.ts";

describe("createHeartbeat", () => {
  it("reports only gaps over the limit and can reset", () => {
    const gaps: number[] = [];
    let t = 0;
    const hb = createHeartbeat(() => t, (g) => void gaps.push(g));
    hb.tick(); // first tick sets the baseline
    for (t of [100, 200]) hb.tick();
    assert.deepEqual(gaps, []);
    t = 600;
    hb.tick();
    assert.deepEqual(gaps, [400]);
    t = 2000;
    hb.reset();
    t = 2100;
    hb.tick();
    assert.deepEqual(gaps, [400]);
  });
});

describe("bucketCounts", () => {
  it("buckets frame deltas", () => {
    assert.deepEqual(bucketCounts([10, 25, 40, 90, 400]), { le20: 1, le34: 1, le50: 1, le100: 1, gt100: 1, frames: 5 });
  });
});

describe("createFrameMeter", () => {
  it("reports deltas once on stop and never runs two loops", () => {
    const queue: Array<(t: number) => void> = [];
    const done: Array<[string, number[]]> = [];
    const m = createFrameMeter({
      raf: (cb) => void queue.push(cb),
      onDone: (k, d) => void done.push([k, d]),
    });
    m.start("pointer");
    m.start("pointer");
    assert.equal(queue.length, 1);
    for (const t of [0, 16, 33, 150]) queue.shift()?.(t);
    m.stop();
    m.stop();
    assert.deepEqual(done, [["pointer", [16, 17, 117]]]);
  });
});
