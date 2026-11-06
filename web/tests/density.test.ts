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
    assert.match(short, /\.ink-rail__gap\s*\{[^}]*height:\s*6px/);
  });
});
