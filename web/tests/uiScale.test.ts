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
import { parseTokenCss } from "../src/ui/tokenTable.ts";

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

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

describe("uiScale.css mirrors the design tokens", () => {
  const scaleCss = read("../src/app/uiScale.css");
  const tokens = parseTokenCss(read("../src/styles/tokens.css"));
  const body = [...scaleCss.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^}]*)\}/g)];
  const decls = new Map<string, string>();
  for (const [, , text] of body) for (const m of text.matchAll(/(--[\w-]+):\s*([^;]+);/g)) decls.set(m[1], m[2].trim());

  const scaled = (value: string, name: string): string => {
    const out = value
      .split(/\s+/)
      .map((part) => {
        if (part === "0") return "0";
        const m = /^(-?[\d.]+)px$/.exec(part);
        assert.ok(m, `${name}: cannot scale ${part}`);
        return `calc(${m[1]}px * var(--ui-scale, 1))`;
      })
      .join(" ");
    return /^--type-(title|reading|control|button|note)-size$/.test(name) ? `max(12px, ${out})` : out;
  };

  it("is a single .ink-shell rule", () => {
    assert.equal(body.length, 1);
    assert.equal(body[0][1].trim(), ".ink-shell");
  });

  it("every override is the token value times --ui-scale", () => {
    for (const [name, value] of decls) {
      const t = tokens.find((x) => x.name === name);
      assert.ok(t, `${name} exists in tokens.css`);
      assert.equal(value, scaled(t.value, name), name);
    }
  });

  it("overrides the sizes the shell reads", () => {
    for (const name of [
      "--space-xs", "--space-sm", "--space-md", "--space-lg", "--space-xl",
      "--type-title-size", "--type-reading-size", "--type-control-size", "--type-button-size", "--type-note-size",
      "--component-tool-rail-width", "--component-tool-rail-padding",
      "--component-top-bar-height", "--component-top-bar-padding",
      "--component-side-panel-width", "--component-side-panel-padding",
      "--component-canvas-card-padding",
      "--component-button-primary-padding", "--component-button-secondary-padding", "--component-button-quiet-padding",
      "--component-draft-badge-padding",
    ]) assert.ok(decls.has(name), name);
  });

  it("never scales the hit area, the corners or the 36 px chip", () => {
    assert.ok(!decls.has("--space-touch"));
    assert.ok(!decls.has("--component-offer-chip-height"));
    for (const name of decls.keys()) assert.ok(!name.startsWith("--radius-"), name);
  });
});
