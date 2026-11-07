import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { LiveDelta } from "../src/sync/liveDelta.ts";
import type { SceneElement } from "../src/sync/sceneSync.ts";

const el = (id: string, version = 1, versionNonce = 0): SceneElement => ({ id, version, versionNonce });

function make(fetchSince: (s: number) => Promise<{ seq: number; elements: SceneElement[] }> = async () => ({ seq: 0, elements: [] })) {
  const applied: SceneElement[][] = [];
  const pen = { down: false };
  const live = new LiveDelta({ origin: "me", isPenDown: () => pen.down, apply: (e) => applied.push(e), fetchSince });
  return { live, applied, pen };
}

describe("LiveDelta", () => {
  it("holds deltas while the pen is down and applies them once on flush", () => {
    const { live, applied, pen } = make();
    pen.down = true;
    live.receive({ seq: 1, origin: "o", elements: [el("a")] });
    live.receive({ seq: 2, origin: "o", elements: [el("b")] });
    assert.equal(applied.length, 0);
    pen.down = false;
    live.flush();
    assert.equal(applied.length, 1);
    assert.deepEqual(applied[0].map((e) => e.id), ["a", "b"]);
  });

  it("keeps the winner for an id regardless of arrival order", () => {
    const { live, applied, pen } = make();
    pen.down = true;
    live.receive({ seq: 1, origin: "o", elements: [el("a", 5)] });
    live.receive({ seq: 2, origin: "o", elements: [el("a", 3)] });
    live.receive({ seq: 3, origin: "o", elements: [el("b", 2, 9)] });
    live.receive({ seq: 4, origin: "o", elements: [el("b", 2, 1)] });
    pen.down = false;
    live.flush();
    assert.deepEqual(applied[0], [el("a", 5), el("b", 2, 1)]);
  });

  it("ignores its own origin", () => {
    const { live, applied } = make();
    live.receive({ seq: 9, origin: "me", elements: [el("a")] });
    live.flush();
    assert.equal(applied.length, 0);
    assert.equal(live.lastSeq, 0);
  });

  it("catchUp fetches since lastSeq, applies when the pen is up and never lowers lastSeq", async () => {
    const asked: number[] = [];
    const { live, applied, pen } = make(async (s) => (asked.push(s), { seq: 7, elements: [el("c")] }));
    live.setSeq(4);
    pen.down = true;
    await live.catchUp();
    assert.deepEqual(asked, [4]);
    assert.equal(live.lastSeq, 7);
    assert.equal(applied.length, 0);
    pen.down = false;
    live.flush();
    assert.equal(applied.length, 1);
    live.receive({ seq: 2, origin: "o", elements: [] });
    assert.equal(live.lastSeq, 7);
  });

  it("swallows a failed catchUp and keeps lastSeq", async () => {
    const { live, applied } = make(async () => {
      throw new Error("offline");
    });
    live.setSeq(3);
    await live.catchUp();
    assert.equal(live.lastSeq, 3);
    assert.equal(applied.length, 0);
  });
});
