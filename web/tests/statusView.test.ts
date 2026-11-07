import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createStatusStore, statusView, RISK_LABEL } from "../src/lib/status.ts";

describe("statusView", () => {
  it("saved is quiet", () => {
    assert.deepEqual(statusView({ state: "saved", detail: "12 ms" }), { tone: "quiet", label: "Saved", title: "12 ms" });
  });
  it("dirty and saving are the soft-ink sending state without a journal, quiet Saved with one", () => {
    for (const state of ["dirty", "saving"] as const) {
      assert.equal(statusView({ state }).tone, "sending");
      assert.deepEqual(statusView({ state }, true), { tone: "quiet", label: "Saved" });
    }
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
    assert.equal(v.label, "Kept on this tablet, sending when the network is back");
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
  it("the store keeps onDevice across state changes and notifies on setDevice", () => {
    const store = createStatusStore();
    let n = 0;
    store.subscribe(() => n++);
    store.setDevice(true);
    store.set("saved");
    assert.equal(store.get().onDevice, true);
    store.setDevice(true);
    assert.equal(n, 2);
  });
});
