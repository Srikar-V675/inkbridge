import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createFingerDraws, loadFingerDraws, saveFingerDraws } from "../src/app/fingerDraws.ts";

function store(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
  };
}
const KEY = "inkbridge-finger-draws";
const broken = {
  getItem: () => { throw new Error("blocked"); },
  setItem: () => { throw new Error("blocked"); },
};

describe("finger draws setting", () => {
  it("defaults to off and loads 1 as on", () => {
    assert.equal(loadFingerDraws(store()), false);
    assert.equal(loadFingerDraws(store({ [KEY]: "1" })), true);
    assert.equal(loadFingerDraws(store({ [KEY]: "0" })), false);
  });
  it("persists 1 and 0", () => {
    const s = store();
    const f = createFingerDraws(s);
    f.set(true);
    assert.equal(s.data[KEY], "1");
    f.set(false);
    assert.equal(s.data[KEY], "0");
    saveFingerDraws(s, true);
    assert.equal(createFingerDraws(s).get(), true);
  });
  it("survives a blocked store and a null store", () => {
    assert.equal(loadFingerDraws(broken), false);
    assert.doesNotThrow(() => saveFingerDraws(broken, true));
    const f = createFingerDraws(broken);
    assert.doesNotThrow(() => f.set(true));
    assert.equal(f.get(), true);
    const n = createFingerDraws(null);
    n.set(true);
    assert.equal(n.get(), true);
  });
  it("notifies once per change and not for a no-op set", () => {
    const f = createFingerDraws(store());
    let n = 0;
    const off = f.subscribe(() => n++);
    f.set(false);
    assert.equal(n, 0);
    f.set(true);
    f.set(true);
    assert.equal(n, 1);
    f.set(false);
    assert.equal(n, 2);
    off();
    f.set(true);
    assert.equal(n, 2);
  });
});
