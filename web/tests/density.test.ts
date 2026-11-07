import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

// Tablet density (INK-170, decision 0074): read the shell CSS as text, as portUi.test.ts does.
const css = readFileSync(fileURLToPath(new URL("../src/app/shell.css", import.meta.url)), "utf8");

/** Body of the first `selector { ... }` rule. Escaped selector; the brace must follow it directly. */
function rule(selector: string, source = css): string {
  const re = new RegExp(`${selector.replace(/[.[\]()]/g, "\\$&")}\\s*\\{([^}]*)\\}`);
  const m = re.exec(source);
  assert.ok(m, `${selector} has a rule`);
  return m[1];
}

/** Body of the first `@media (query) { ... }` block, up to its closing brace at column 0. */
function media(query: string): string {
  const start = css.indexOf(`@media ${query} {`);
  assert.ok(start >= 0, `@media ${query} exists`);
  const end = css.indexOf("\n}", start);
  return css.slice(start, end);
}

describe("tablet rail (INK-170, decision 0074)", () => {
  it("the rail is capped to the dynamic viewport and scrolls when still too tall", () => {
    const r = rule(".ink-rail");
    const vh = r.indexOf("max-height: calc(100vh - var(--ink-rail-top) - var(--space-md))");
    const dvh = r.indexOf("max-height: calc(100dvh - var(--ink-rail-top) - var(--space-md))");
    assert.ok(vh >= 0, "100vh fallback");
    assert.ok(dvh > vh, "100dvh declaration follows the fallback");
    assert.match(r, /overflow-y:\s*auto/);
    assert.match(r, /overflow-x:\s*hidden/);
    assert.match(r, /overscroll-behavior:\s*contain/);
    assert.match(r, /top:\s*var\(--ink-rail-top\)/);
  });

  it("compact when the screen is short: no gaps between tools, 6 px section gap", () => {
    const short = media("(max-height: 720px)");
    assert.match(short, /\.ink-rail\s*\{[^}]*gap:\s*0/);
    assert.match(short, /\.ink-rail__gap\s*\{[^}]*height:\s*calc\(6px \* var\(--ui-scale, 1\)\)/);
  });

  it("the rail top clears the scaled top bar at every size (INK-177)", () => {
    assert.match(rule(".ink-shell"), /--ink-rail-top:\s*calc\(88px \* var\(--ui-scale, 1\)\)/);
    assert.match(media("(max-height: 720px)"), /\.ink-shell\s*\{\s*--ink-rail-top:\s*calc\(72px \* var\(--ui-scale, 1\)\)/);
    assert.match(media("(pointer: coarse), (max-width: 1300px)"), /\.ink-shell\s*\{\s*--ink-rail-top:\s*calc\(72px \* var\(--ui-scale, 1\)\)/);
    assert.match(rule(".ink-rail__gap"), /height:\s*calc\(12px \* var\(--ui-scale, 1\)\)/);
  });
});

describe("compact zoom pill (INK-170, INK-177): 36 px visual at Large, 44 px hit area at every size", () => {
  const S = "var(--ui-scale, 1)";

  it("the pill is 36 px tall at Large, with no hex and no old 148 px width", () => {
    const r = rule(".ink-zoom");
    assert.match(r, new RegExp(`height:\\s*calc\\(36px \\* ${S.replace(/[()]/g, "\\$&")}\\)`));
    assert.doesNotMatch(r, /#[0-9a-f]{3,8}\b/i);
    assert.doesNotMatch(r, /148px/);
    assert.match(r, /right:\s*calc\(20px \* var\(--ui-scale, 1\)\)/);
    assert.match(r, /bottom:\s*calc\(20px \* var\(--ui-scale, 1\)\)/);
  });

  it("its icon buttons are 32 px at Large, and a pseudo-element gives a 44 px hit area", () => {
    const b = rule(".ink-zoom .ink-icon-button");
    for (const p of ["width", "min-width", "height", "min-height"]) {
      assert.match(b, new RegExp(`(^|[\\s;])${p}:\\s*calc\\(32px \\* var\\(--ui-scale, 1\\)\\)`), p);
    }
    const after = rule(".ink-zoom .ink-icon-button::after");
    assert.match(after, /position:\s*absolute/);
    assert.match(after, /inset:\s*min\(0px, calc\(\(32px \* var\(--ui-scale, 1\) - var\(--space-touch\)\) \/ 2\)\)/);
    for (const s of [0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2]) {
      const inset = Math.min(0, (32 * s - 44) / 2);
      assert.ok(32 * s + 2 * -inset >= 44 - 1e-9, `scale ${s}`);
    }
    assert.match(rule(".ink-zoom__value"), /min-width:\s*calc\(40px \* var\(--ui-scale, 1\)\)/);
  });
});

describe("tablet density (INK-170): smaller top bar type, touch targets stay 44 px", () => {
  const tablet = "(pointer: coarse), (max-width: 1300px)";

  it("the top bar shrinks on tablets and narrow windows, appended after the short-screen block", () => {
    const start = css.indexOf(`@media ${tablet} {`);
    assert.ok(start > css.indexOf("@media (max-height: 720px)"), "appended after the rail block");
    const body = media(tablet);
    assert.match(body, /\.ink-topbar__title\s*\{[^}]*font-size:\s*max\(12px, calc\(18px \* var\(--ui-scale, 1\)\)\)/);
    assert.match(body, /\.ink-topbar__status\s*\{[^}]*font-size:\s*max\(12px, calc\(13px \* var\(--ui-scale, 1\)\)\)/);
    assert.match(body, /\.ink-topbar\s*\{[^}]*gap:\s*var\(--space-sm\)/);
  });

  it("no button rule goes below 44 px outside the zoom pill", () => {
    const rules = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)];
    for (const [, selector, body] of rules) {
      if (!/\.ink-(icon-)?button\b/.test(selector) || selector.includes(".ink-zoom")) continue;
      assert.doesNotMatch(body, /height:\s*3\d(\.\d+)?px/, selector.trim());
    }
  });
});

describe("properties card follows the scale (INK-177)", () => {
  const props = readFileSync(fileURLToPath(new URL("../src/app/props/props.css", import.meta.url)), "utf8");
  it("clears the scaled rail and is 280 px at Large", () => {
    const r = rule(".ink-props.ink-card", props);
    assert.match(r, /left:\s*calc\(2 \* var\(--space-md\) \+ var\(--component-tool-rail-width\)\)/);
    assert.match(r, /width:\s*calc\(280px \* var\(--ui-scale, 1\)\)/);
    assert.match(rule(".ink-props__value", props), /min-width:\s*calc\(48px \* var\(--ui-scale, 1\)\)/);
  });
});
