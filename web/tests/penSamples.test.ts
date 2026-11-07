import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createPenSamples, installPenSamples, type SampleEvent } from "../src/ink/penSamples.ts";

const ev = (pointerId: number, x: number, y: number, pressure = 0.5, coalesced?: SampleEvent[]): SampleEvent => ({
  pointerId,
  clientX: x,
  clientY: y,
  pressure,
  ...(coalesced && { getCoalescedEvents: () => coalesced }),
});

describe("createPenSamples", () => {
  it("keeps every coalesced sample of a move, in order, until taken", () => {
    const s = createPenSamples();
    s.down(ev(1, 0, 0));
    const last = ev(1, 3, 3, 0.7, [ev(1, 1, 1, 0.5), ev(1, 2, 2, 0.6), ev(1, 3, 3, 0.7)]);
    s.move(last);
    s.move(ev(1, 4, 4, 0.8)); // no coalesced list: the event itself
    assert.deepEqual(s.peek(1).map((p) => p.clientX), [1, 2, 3, 4]);
    assert.deepEqual(s.take(last)?.map((p) => [p.clientX, p.pressure]), [[1, 0.5], [2, 0.6], [3, 0.7], [4, 0.8]]);
    assert.deepEqual(s.take(last), []); // taken once
  });

  it("uses the event when the coalesced list is empty or throws", () => {
    const s = createPenSamples();
    s.down(ev(1, 0, 0));
    s.move(ev(1, 5, 5, 0.5, []));
    s.move({ ...ev(1, 6, 6), getCoalescedEvents: () => { throw new Error("insecure context"); } });
    assert.deepEqual(s.take(ev(1, 0, 0))?.map((p) => p.clientX), [5, 6]);
  });

  it("keeps pointers apart and answers null for a pointer it never saw go down", () => {
    const s = createPenSamples();
    s.down(ev(1, 0, 0));
    s.down(ev(2, 0, 0));
    s.move(ev(2, 9, 9));
    s.move(ev(3, 7, 7)); // never went down: ignored
    assert.deepEqual(s.take(ev(1, 0, 0)), []);
    assert.deepEqual(s.take(ev(2, 0, 0))?.map((p) => p.clientX), [9]);
    assert.equal(s.take(ev(3, 0, 0)), null);
  });

  it("a new down drops what an earlier stroke left behind", () => {
    const s = createPenSamples();
    s.down(ev(1, 0, 0));
    s.move(ev(1, 1, 1));
    s.down(ev(1, 0, 0));
    assert.deepEqual(s.take(ev(1, 0, 0)), []);
  });

  it("caps a buffer nobody takes", () => {
    const s = createPenSamples(3);
    s.down(ev(1, 0, 0));
    for (let i = 1; i <= 5; i++) s.move(ev(1, i, i));
    assert.deepEqual(s.peek(1).map((p) => p.clientX), [3, 4, 5]);
  });
});

describe("installPenSamples", () => {
  it("registers capture listeners and the hook the Excalidraw patch calls, and removes both", () => {
    const added: Array<[string, boolean]> = [];
    const removed: string[] = [];
    const handlers = new Map<string, (e: SampleEvent) => void>();
    const g: { __inkbridgePenSamples?: unknown } = {};
    const win = {
      addEventListener: (t: string, cb: (e: SampleEvent) => void, o: { capture: boolean }) => (added.push([t, o.capture]), handlers.set(t, cb)),
      removeEventListener: (t: string) => void removed.push(t),
    };
    const off = installPenSamples(win, g);
    assert.deepEqual(added, [["pointerdown", true], ["pointermove", true]]);
    handlers.get("pointerdown")!(ev(4, 0, 0));
    handlers.get("pointermove")!(ev(4, 2, 2));
    const hook = g.__inkbridgePenSamples as (e: SampleEvent) => unknown;
    assert.deepEqual((hook(ev(4, 0, 0)) as { clientX: number }[]).map((p) => p.clientX), [2]);
    off();
    assert.deepEqual(removed, ["pointerdown", "pointermove"]);
    assert.equal(g.__inkbridgePenSamples, undefined);
  });
});
