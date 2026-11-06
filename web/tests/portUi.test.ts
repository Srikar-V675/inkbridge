import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { parseTokenCss, resolveVar } from "../src/ui/tokenTable.ts";

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

describe("draft bar css (INK-162)", () => {
  const css = read("drafts/DraftBar.css");
  it("the tray and card use tokens, the card is dashed charcoal, never the agent colour", () => {
    assert.match(css, /\.ink-draft-card\s*\{[^}]*dashed var\(--color-charcoal\)/);
    assert.match(css, /\.ink-draft-tray\s*\{[^}]*background:\s*var\(--color-charcoal\)/);
  });
  it("DraftBar composes Button, Badge, Chip and Toast, not raw buttons", () => {
    const tsx = read("drafts/DraftBar.tsx");
    assert.ok(!tsx.includes("<button"));
    for (const name of ["Button", "Badge", "Chip", "Toast", "DraftDot"]) assert.ok(tsx.includes(name), name);
  });
});

describe("chunk overlay css (INK-162)", () => {
  const css = read("chunks/ChunkOverlay.css");
  const tokens = parseTokenCss(read("styles/tokens.css"));
  const px = (v: string) => Number(/^(-?[\d.]+)px$/.exec(resolveVar(tokens, v.trim()))?.[1]);
  it("the chunk tab is a 44 px target", () => {
    const rule = /\.ink-chunk-tab\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    assert.ok(px(/min-height:\s*([^;]+)/.exec(rule)?.[1] ?? "") >= 44);
    assert.ok(px(/min-width:\s*([^;]+)/.exec(rule)?.[1] ?? "") >= 44);
  });
  it("ChunkOverlay has no raw colours or inline styles for chrome", () => {
    const tsx = read("chunks/ChunkOverlay.tsx");
    assert.ok(!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(tsx));
    assert.ok(!tsx.includes("Show chunks"));
  });
});

describe("jump notice and ghost (INK-162 review)", () => {
  it("the ghost outlives the toast timeout; only the user's Dismiss closes it", () => {
    const notice = read("chunks/JumpNotice.tsx");
    assert.match(notice, /onDismiss=\{onExpire\}/);
    assert.match(notice, /onAction=\{onClose\}/);
    const app = read("app/App.tsx");
    assert.match(app, /ghostOpen/);
    assert.match(app, /ghost=\{ghostOpen &&/);
  });
});
