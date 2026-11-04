import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createRefresh, onVisible } from "../src/chunkRefresh.ts";

function fakeTimers() {
  const pending: Array<() => void> = [];
  return {
    pending,
    setTimer: (fn: () => void) => {
      pending.push(fn);
    },
    runAll() {
      const run = pending.splice(0);
      run.forEach((fn) => fn());
    },
  };
}

function fakeDoc(visibilityState: string) {
  const listeners = new Map<string, Set<() => void>>();
  return {
    visibilityState,
    addEventListener(t: string, f: () => void) {
      if (!listeners.has(t)) listeners.set(t, new Set());
      listeners.get(t)!.add(f);
    },
    removeEventListener(t: string, f: () => void) {
      listeners.get(t)?.delete(f);
    },
    dispatch(t: string) {
      listeners.get(t)?.forEach((f) => f());
    },
    count(t: string) {
      return listeners.get(t)?.size ?? 0;
    },
  };
}

describe("createRefresh", () => {
  it("coalesces a burst into one listener call, and fires again for a later burst", () => {
    const timers = fakeTimers();
    const r = createRefresh(800, timers.setTimer);
    let calls = 0;
    r.subscribe(() => calls++);
    r.fire();
    r.fire();
    r.fire();
    assert.equal(timers.pending.length, 1);
    assert.equal(calls, 0);
    timers.runAll();
    assert.equal(calls, 1);
    r.fire();
    timers.runAll();
    assert.equal(calls, 2);
  });

  it("does not call an unsubscribed listener", () => {
    const timers = fakeTimers();
    const r = createRefresh(800, timers.setTimer);
    let calls = 0;
    const off = r.subscribe(() => calls++);
    r.fire();
    off();
    timers.runAll();
    assert.equal(calls, 0);
  });
});

describe("onVisible", () => {
  it("calls fn only when the document becomes visible, and unsubscribes", () => {
    const doc = fakeDoc("visible");
    let calls = 0;
    const off = onVisible(doc, () => calls++);
    doc.visibilityState = "hidden";
    doc.dispatch("visibilitychange");
    assert.equal(calls, 0);
    doc.visibilityState = "visible";
    doc.dispatch("visibilitychange");
    assert.equal(calls, 1);
    off();
    assert.equal(doc.count("visibilitychange"), 0);
  });
});
