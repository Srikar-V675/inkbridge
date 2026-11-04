import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createRefresh, onVisible, wireRefresh, type Refresh } from "../src/chunkRefresh.ts";

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

describe("createRefresh dispose", () => {
  it("clears a pending burst, and the signal works again afterwards", () => {
    const cleared: unknown[] = [];
    const timers: Array<() => void> = [];
    const r = createRefresh(800, (fn) => (timers.push(fn), timers.length), (h) => cleared.push(h));
    let calls = 0;
    r.subscribe(() => calls++);
    r.fire();
    r.dispose();
    assert.deepEqual(cleared, [1]);
    r.fire();
    assert.equal(timers.length, 2);
    timers[1]();
    assert.equal(calls, 1);
  });
});

function countingRefresh() {
  let fires = 0;
  const r: Refresh = { fire: () => void fires++, subscribe: () => () => {}, dispose: () => {} };
  return { r, fires: () => fires };
}

describe("wireRefresh", () => {
  it("fires on a chunk push", () => {
    const c = countingRefresh();
    const w = wireRefresh(c.r, fakeDoc("hidden"));
    w.onChunksUpdated();
    assert.equal(c.fires(), 1);
    w.off();
  });

  it("fires on connect only, not on disconnect", () => {
    const c = countingRefresh();
    const w = wireRefresh(c.r, fakeDoc("hidden"));
    w.onConnection(false);
    assert.equal(c.fires(), 0);
    w.onConnection(true);
    assert.equal(c.fires(), 1);
    w.off();
  });

  it("fires when the document becomes visible, and off() stops it", () => {
    const c = countingRefresh();
    const doc = fakeDoc("hidden");
    const w = wireRefresh(c.r, doc);
    doc.dispatch("visibilitychange");
    assert.equal(c.fires(), 0);
    doc.visibilityState = "visible";
    doc.dispatch("visibilitychange");
    assert.equal(c.fires(), 1);
    w.off();
    doc.dispatch("visibilitychange");
    assert.equal(c.fires(), 1);
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
