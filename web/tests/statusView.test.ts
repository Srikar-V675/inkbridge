import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { statusView, RISK_LABEL } from "../src/lib/status.ts";

describe("statusView", () => {
  it("saved is quiet", () => {
    assert.deepEqual(statusView({ state: "saved", detail: "12 ms" }), { tone: "quiet", label: "Saved", title: "12 ms" });
  });
  it("dirty and saving are the soft-ink sending state", () => {
    for (const state of ["dirty", "saving"] as const) assert.equal(statusView({ state }).tone, "sending");
  });
  it("retry is the alarm while nothing is stored on the device", () => {
    const v = statusView({ state: "retry", detail: "Offline, retrying" });
    assert.equal(v.tone, "risk");
    assert.equal(v.label, "Ink only in memory: do not close this tab");
    assert.equal(RISK_LABEL, v.label);
  });
  it("retry is soft-ink once the ink is kept on the device", () => {
    const v = statusView({ state: "retry" }, true);
    assert.equal(v.tone, "sending");
    assert.equal(v.label, "Kept on this device, sending when the network is back");
  });
  it("error shows its own words in the alarm, or the risk line when it has none", () => {
    assert.deepEqual(statusView({ state: "error", detail: "Save rejected (422); changes are not saved yet" }), {
      tone: "risk", label: "Save rejected (422); changes are not saved yet",
    });
    assert.equal(statusView({ state: "error" }).label, RISK_LABEL);
  });
  it("loading has no dot", () => {
    assert.equal(statusView({ state: "loading" }).tone, "none");
  });
  it("conflict says it merged and shows its detail as visible text, not only a hover title", () => {
    const v = statusView({ state: "conflict", detail: "Another device saved first; merged its changes with yours" });
    assert.equal(v.tone, "notice");
    assert.equal(v.label, "Merged with another device");
    assert.equal(v.detail, "Another device saved first; merged its changes with yours");
    assert.ok(!v.label.includes("Merging"));
  });
});
