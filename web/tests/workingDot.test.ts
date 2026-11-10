import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createActivityStore, HIDE_MS, type ActivityMsg } from "../src/app/activity.ts";

const msg = (o: Partial<ActivityMsg> = {}): ActivityMsg => ({
  type: "agent.activity",
  working: true,
  what: "reading",
  count: 1,
  ...o,
});

// A timer the test fires by hand, so the 1 s hide is exact.
function fakeTimers() {
  let next = 0;
  const pending = new Map<number, () => void>();
  return {
    setTimer: (fn: () => void, ms: number) => {
      assert.equal(ms, HIDE_MS);
      pending.set(++next, fn);
      return next;
    },
    clearTimer: (id: unknown) => {
      pending.delete(id as number);
    },
    fire: () => {
      for (const [id, fn] of [...pending]) {
        pending.delete(id);
        fn();
      }
    },
    count: () => pending.size,
  };
}

describe("working dot state", () => {
  it("shows the reading label while the agent reads", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    s.apply(msg());
    assert.deepEqual(s.get(), { visible: true, label: "Reading your handwriting" });
  });

  it("labels tasks and answers, and counts items in flight", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    s.apply(msg({ what: "task" }));
    assert.equal(s.get().label, "Working on a task");
    s.apply(msg({ what: "answer", count: 2 }));
    assert.equal(s.get().label, "Answering your question (2)");
  });

  it("stays visible after idle until the 1 s timer, and a new burst cancels the hide", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    s.apply(msg());
    s.apply(msg({ working: false, count: 0 }));
    assert.equal(s.get().visible, true);
    assert.equal(t.count(), 1);
    s.apply(msg()); // a read starts before the timer fires
    assert.equal(t.count(), 0);
    s.apply(msg({ working: false, count: 0 }));
    t.fire();
    assert.deepEqual(s.get(), { visible: false, label: "" });
  });

  it("hides at once when the socket closes", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    s.apply(msg());
    s.reset();
    assert.deepEqual(s.get(), { visible: false, label: "" });
    assert.equal(t.count(), 0);
  });

  it("ignores a malformed message", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    s.apply(msg({ working: "yes" as unknown as boolean }));
    s.apply(msg({ what: "dancing" as never }));
    assert.deepEqual(s.get(), { visible: false, label: "" });
  });

  it("notifies subscribers on change", () => {
    const t = fakeTimers();
    const s = createActivityStore(t.setTimer, t.clearTimer);
    let n = 0;
    const off = s.subscribe(() => n++);
    s.apply(msg());
    off();
    s.apply(msg({ what: "task" }));
    assert.equal(n, 1);
  });
});
