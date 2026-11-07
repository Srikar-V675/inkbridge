import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import {
  UI_KEY,
  createUiScale,
  defaultScale,
  loadUiScale,
  nextSize,
  parseUiParam,
  saveUiScale,
  sizeLabel,
  sizeShort,
} from "../src/app/uiScale.ts";

function store(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
    removeItem: (k: string) => void delete data[k],
  };
}
const broken = {
  getItem: () => { throw new Error("blocked"); },
  setItem: () => { throw new Error("blocked"); },
  removeItem: () => { throw new Error("blocked"); },
};

describe("UI size setting (INK-177, decision 0083)", () => {
  it("defaults to Small on a coarse pointer and Large otherwise", () => {
    assert.equal(defaultScale(true), 0.8);
    assert.equal(defaultScale(false), 1);
  });

  it("loads a stored value in range and falls back to the default otherwise", () => {
    assert.equal(loadUiScale(store({ [UI_KEY]: "0.9" }), true), 0.9);
    assert.equal(loadUiScale(store({ [UI_KEY]: "0.6" }), false), 0.6);
    assert.equal(loadUiScale(store({ [UI_KEY]: "1.2" }), false), 1.2);
    assert.equal(loadUiScale(store(), true), 0.8);
    assert.equal(loadUiScale(null, false), 1);
    assert.equal(loadUiScale(broken, true), 0.8);
    assert.equal(loadUiScale(store({ [UI_KEY]: "abc" }), false), 1);
    assert.equal(loadUiScale(store({ [UI_KEY]: "0.3" }), true), 0.8);
    assert.equal(loadUiScale(store({ [UI_KEY]: "2" }), true), 0.8);
  });

  it("saves the value as a string and swallows a blocked store", () => {
    const s = store();
    saveUiScale(s, 0.7);
    assert.equal(s.data[UI_KEY], "0.7");
    assert.doesNotThrow(() => saveUiScale(broken, 0.7));
    assert.doesNotThrow(() => saveUiScale(null, 0.7));
  });

  it("reads ?ui= from the URL", () => {
    assert.equal(parseUiParam("?ui=0.7"), 0.7);
    assert.equal(parseUiParam("?canvas=a&ui=0.9"), 0.9);
    assert.equal(parseUiParam("?ui=abc"), null);
    assert.equal(parseUiParam("?ui=0.3"), null);
    assert.equal(parseUiParam("?ui=9"), null);
    assert.equal(parseUiParam(""), null);
    assert.equal(parseUiParam("?ui=0"), "clear");
  });

  it("applies and remembers ?ui=, clears it with ?ui=0, and prefers a stored value", () => {
    const s = store();
    const a = createUiScale(s, { coarse: true, search: "?ui=0.7" });
    assert.equal(a.get(), 0.7);
    assert.equal(s.data[UI_KEY], "0.7");

    const b = createUiScale(s, { coarse: true, search: "?ui=0" });
    assert.equal(b.get(), 0.8);
    assert.equal(s.data[UI_KEY], undefined);

    assert.equal(createUiScale(store({ [UI_KEY]: "0.9" }), { coarse: true, search: "" }).get(), 0.9);
    assert.equal(createUiScale(store(), { coarse: false, search: "" }).get(), 1);
    assert.equal(createUiScale(broken, { coarse: true, search: "?ui=0" }).get(), 0.8);
  });

  it("set persists and notifies once; the same value or an invalid one does not", () => {
    const s = store();
    const u = createUiScale(s, { coarse: false, search: "" });
    let n = 0;
    const off = u.subscribe(() => n++);
    u.set(0.9);
    assert.equal(u.get(), 0.9);
    assert.equal(s.data[UI_KEY], "0.9");
    assert.equal(n, 1);
    u.set(0.9);
    u.set(5);
    u.set(Number.NaN);
    assert.equal(n, 1);
    assert.equal(u.get(), 0.9);
    u.cycle();
    assert.equal(u.get(), 1);
    assert.equal(n, 2);
    off();
    u.set(0.8);
    assert.equal(n, 2);
  });

  it("cycles Small, Medium, Large and moves a custom value to the next larger preset", () => {
    assert.equal(nextSize(0.8), 0.9);
    assert.equal(nextSize(0.9), 1);
    assert.equal(nextSize(1), 0.8);
    assert.equal(nextSize(0.7), 0.8);
    assert.equal(nextSize(1.1), 0.8);
  });

  it("labels the presets and shows a custom value as a number", () => {
    assert.equal(sizeLabel(0.8), "Small");
    assert.equal(sizeLabel(0.9), "Medium");
    assert.equal(sizeLabel(1), "Large");
    assert.equal(sizeLabel(0.7), "0.7");
    assert.equal(sizeShort(0.8), "S");
    assert.equal(sizeShort(0.9), "M");
    assert.equal(sizeShort(1), "L");
    assert.equal(sizeShort(0.7), "0.7");
  });
});
