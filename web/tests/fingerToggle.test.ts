import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const src = (p: string) => readFileSync(new URL(`../src/app/${p}`, import.meta.url), "utf8");

describe("Finger draws toggle look", () => {
  it("has its own class, not the shared chunk toggle class", () => {
    const tsx = src("TouchLayer.tsx");
    assert.match(tsx, /className="ink-finger-toggle"/);
    assert.doesNotMatch(tsx, /ink-chunk-toggle/);
  });
  it("on is a charcoal fill that beats the quiet hover colour", () => {
    const css = src("TouchLayer.css");
    assert.match(css, /\.ink-button\.ink-finger-toggle\[aria-pressed="true"\][^{]*\{[^}]*background:\s*var\(--color-charcoal\)/);
    assert.match(css, /color:\s*var\(--color-paper\)/);
  });
  it("off never keeps a hover tint on touch screens", () => {
    const css = src("TouchLayer.css");
    assert.match(css, /@media \(hover: none\)[\s\S]*\[aria-pressed="false"\]:hover[\s\S]*var\(--component-button-quiet-background-color\)/);
  });
});
