import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { probeLoop, probeState, runProbes } from "../src/lib/probe.ts";
import type { ProbeRecord } from "../src/lib/probe.ts";

describe("probeLoop", () => {
  it("emits one record per request and carries on after a failure", async () => {
    const out: Array<{ name: string; counts: Record<string, number> }> = [];
    let n = 0;
    await probeLoop({
      side: "main",
      state: "idle",
      count: 3,
      send: async () => { if (n++ === 1) throw new Error("net"); },
      emit: (r) => void out.push(r),
      wait: async () => {},
      now: () => 0,
    });
    assert.deepEqual(out.map((r) => r.name), Array(3).fill("probe.main.idle"));
    assert.deepEqual(out.map((r) => r.counts.seq), [0, 1, 2]);
    assert.deepEqual(out.map((r) => r.counts.ok), [1, 0, 1]);
    assert.equal(out[0].counts.bytes, 4096);
  });
});

describe("runProbes", () => {
  it("one run writes both series, and a bad state falls back to idle", async () => {
    const names: string[] = [];
    await runProbes({
      state: "writing",
      count: 2,
      send: async () => {},
      wait: async () => {},
      emit: (r) => void names.push(r.name),
      startWorker: (onMessage) => onMessage({ name: "probe.worker.writing", ms: 7, counts: { seq: 0 }, t: 5 } as ProbeRecord),
    });
    assert.ok(names.includes("probe.main.writing") && names.includes("probe.worker.writing"));
    assert.equal(probeState("Bad State!"), "idle");
    assert.equal(probeState("panning"), "panning");
    assert.equal(probeState(null), "idle");
  });
});
