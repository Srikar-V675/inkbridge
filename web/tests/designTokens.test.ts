import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { buildTokensCss, parseFrontMatter } from "../scripts/design-tokens.mjs";
import { parseTokenCss, resolveVar } from "../src/ui/tokenTable.ts";

const md = readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const tokens = parseTokenCss(css);
const get = (name: string) => tokens.find((t) => t.name === name)?.value;

describe("design tokens", () => {
  it("committed tokens.css equals buildTokensCss(DESIGN.md)", () => {
    assert.equal(css, buildTokensCss(md));
  });

  it("output follows the input", () => {
    assert.ok(buildTokensCss(md.replace("#D4F23A", "#000001")).includes("--color-lime: #000001;"));
  });

  it("spot checks on the committed file", () => {
    assert.equal(get("--color-lime"), "#D4F23A");
    assert.equal(get("--color-alarm"), "#B3261E");
    assert.equal(get("--radius-pill"), "18px");
    assert.equal(get("--space-touch"), "44px");
    assert.equal(get("--type-reading-line-height"), "1.45");
    assert.equal(get("--type-wordmark-tracking"), "-0.02em");
    assert.ok(get("--type-button-family")?.startsWith('"Instrument Sans"'));
    assert.equal(get("--component-button-primary-height"), "44px");
    assert.equal(get("--component-offer-chip-height"), "36px");
    assert.equal(get("--component-button-primary-background-color"), "var(--color-charcoal)");
    assert.equal(get("--component-side-panel-width"), "440px");
    assert.equal(get("--shadow-popover"), "0 10px 28px rgba(46, 45, 43, 0.16)");
  });

  it("every front matter colour, rounded and spacing key has a variable", () => {
    const fm = parseFrontMatter(md);
    for (const [group, prefix] of [["colors", "color"], ["rounded", "radius"], ["spacing", "space"]] as const)
      for (const key of Object.keys(fm[group])) assert.ok(get(`--${prefix}-${key}`) !== undefined, `--${prefix}-${key}`);
  });

  it("parseTokenCss and resolveVar follow var chains", () => {
    assert.equal(resolveVar(tokens, "var(--component-button-primary-background-color)"), "#2E2D2B");
    assert.equal(resolveVar(tokens, "var(--nope)"), "var(--nope)");
    assert.equal(resolveVar(tokens, " 12px "), "12px");
  });
});
