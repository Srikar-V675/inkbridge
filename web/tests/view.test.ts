import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { keepFittingFirstDrafts, loadView, saveView } from "../src/view.ts";

function store(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
  };
}

describe("per-canvas view", () => {
  it("returns null when nothing is saved", () => {
    assert.equal(loadView(store(), "default"), null);
  });

  it("round-trips scroll and zoom, keyed by canvas", () => {
    const s = store();
    saveView(s, "default", { scrollX: -120.5, scrollY: 300, zoom: 0.75 });
    saveView(s, "other", { scrollX: 1, scrollY: 2, zoom: 2 });
    assert.deepEqual(loadView(s, "default"), { scrollX: -120.5, scrollY: 300, zoom: 0.75 });
    assert.deepEqual(loadView(s, "other"), { scrollX: 1, scrollY: 2, zoom: 2 });
  });

  it("ignores corrupt or non-numeric saved values", () => {
    assert.equal(loadView(store({ "inkbridge-view-default": "{nope" }), "default"), null);
    const bad = JSON.stringify({ scrollX: "a", scrollY: 1, zoom: 1 });
    assert.equal(loadView(store({ "inkbridge-view-default": bad }), "default"), null);
    const inf = '{"scrollX":1,"scrollY":1,"zoom":0}';
    assert.equal(loadView(store({ "inkbridge-view-default": inf }), "default"), null);
  });

  it("does not save non-finite values and survives a throwing storage", () => {
    const s = store();
    saveView(s, "default", { scrollX: NaN, scrollY: 0, zoom: 1 });
    assert.deepEqual(s.data, {});
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    assert.equal(loadView(broken, "default"), null);
    assert.doesNotThrow(() => saveView(broken, "default", { scrollX: 0, scrollY: 0, zoom: 1 }));
  });

  it("clamps an out-of-range zoom when loading", () => {
    const s = store({ "inkbridge-view-default": JSON.stringify({ scrollX: 0, scrollY: 0, zoom: 500 }) });
    assert.equal(loadView(s, "default")?.zoom, 30);
  });
});

describe("fit to first drafts", () => {
  const armed = { scrollX: 0, scrollY: 0, zoom: 1 };
  const draft = { customData: { draft: true, op_id: "a" } };
  it("keeps fitting while only drafts exist and the view is untouched", () => {
    assert.equal(keepFittingFirstDrafts(armed, { ...armed }, []), true);
    assert.equal(keepFittingFirstDrafts(armed, { ...armed }, [draft]), true);
    assert.equal(keepFittingFirstDrafts(armed, { ...armed }, [{ isDeleted: true }]), true);
  });
  it("stops once the user pans, zooms or draws", () => {
    assert.equal(keepFittingFirstDrafts(armed, { ...armed, scrollX: 5 }, []), false);
    assert.equal(keepFittingFirstDrafts(armed, { ...armed, zoom: 1.5 }, []), false);
    assert.equal(keepFittingFirstDrafts(armed, { ...armed }, [{ customData: {} }]), false);
  });
});
