import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");
const zOf = (css: string, selector: string): number => {
  const m = new RegExp(`${selector.replace(/[.]/g, "\\.")}\\s*\\{[^}]*z-index:\\s*(\\d+)`).exec(css);
  assert.ok(m, `${selector} has a z-index`);
  return Number(m[1]);
};

describe("shell layers (decision 0068)", () => {
  const css = read("app/shell.css");
  it("overlays sit above the rail and zoom control, below the top bar controls", () => {
    assert.ok(zOf(css, ".ink-shell__overlays") > zOf(css, ".ink-rail"));
    assert.ok(zOf(css, ".ink-shell__overlays") > zOf(css, ".ink-zoom"));
    assert.ok(zOf(css, ".ink-topbar") > zOf(css, ".ink-shell__overlays"));
  });
  it("the overlays layer is outside the canvas wrapper and lets the pen through", () => {
    const shell = read("app/Shell.tsx");
    assert.ok(shell.indexOf("ink-shell__overlays") > shell.indexOf("</div>"), "rendered after the canvas div closes");
    assert.match(css, /\.ink-shell__overlays\s*\{[^}]*pointer-events:\s*none/);
  });
});
