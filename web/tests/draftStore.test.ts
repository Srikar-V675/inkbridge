import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createDraftStore, offsetOf, reconcile, type PlacedOp } from "../src/drafts/draftStore.ts";
import type { DraftElement } from "../src/drafts/drafts.ts";

const el = (o: Record<string, unknown>) => o as unknown as DraftElement;
const op = (id: string, xs: DraftElement[] = [el({ id: `${id}:1`, type: "text", x: 100, y: 50, width: 10, height: 5 })]): PlacedOp => ({
  id,
  payload: { id_prefix: `${id}:` },
  elements: xs,
  box: { x: 100, y: 50, width: 10, height: 5 },
});
const user = el({ id: "u1", type: "freedraw", x: 0, y: 0 });

describe("reconcile", () => {
  it("adds a placed op once, tagged as a draft", () => {
    const once = reconcile([user], [op("a")]);
    assert.equal(once.length, 2);
    assert.equal(once[1].customData?.draft, true);
    assert.equal(once[1].customData?.op_id, "a");
    const twice = reconcile(once, [op("a")]);
    assert.equal(twice, once);
  });
  it("removes live drafts whose op is gone", () => {
    const withDraft = reconcile([user], [op("a")]);
    assert.deepEqual(reconcile(withDraft, []).map((e) => e.id), ["u1"]);
  });
  it("never touches a user element with a forged tag but no prefixed id", () => {
    const forged = el({ id: "zzz", type: "text", x: 0, y: 0, customData: { draft: true, op_id: "a" } });
    assert.ok(reconcile([forged], []).includes(forged));
  });
  it("keeps a dragged draft where the user put it", () => {
    const first = reconcile([], [op("a")]);
    const moved = first.map((e) => ({ ...e, x: 400 }));
    assert.equal(reconcile(moved, [op("a")])[0].x, 400);
  });
  it("brings a draft back over the solid element an unaccept deleted", () => {
    const solid = el({ id: "a:1", type: "text", x: 100, y: 50, isDeleted: true, version: 3 });
    const out = reconcile([user, solid], [op("a")]);
    assert.deepEqual(out.map((e) => [e.id, e.isDeleted ?? false]), [["u1", false], ["a:1", false]]);
    assert.equal(out[1].customData?.draft, true);
  });
  it("does not bring back an erased draft", () => {
    const first = reconcile([], [op("a")]);
    const erased = first.map((e) => ({ ...e, isDeleted: true }));
    assert.equal(reconcile(erased, [op("a")]), erased);
  });
});

describe("offsetOf", () => {
  it("is 0,0 untouched and the drag otherwise, rounded", () => {
    const o = op("a");
    const scene = reconcile([], [o]);
    assert.deepEqual(offsetOf(scene, o), { dx: 0, dy: 0 });
    const moved = scene.map((e) => ({ ...e, x: e.x + 12.3456, y: e.y - 7 }));
    assert.deepEqual(offsetOf(moved, o), { dx: 12.35, dy: -7 });
  });
});

describe("store", () => {
  it("notifies once per change and keeps arrival order", () => {
    const s = createDraftStore();
    let n = 0;
    s.subscribe(() => n++);
    s.set([op("a")]);
    s.upsert(op("b"));
    s.upsert(op("a"));
    s.remove("b");
    s.remove("nope");
    assert.equal(n, 4);
    assert.deepEqual(s.ids(), ["a"]);
  });
});
