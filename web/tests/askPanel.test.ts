// Source-level rules for the Ask panel (INK-161, docs/decisions/0067): no DOM harness exists (decision 0046).
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");
const askFiles = () => readdirSync(join(SRC, "ask")).map((f) => [f, read(`ask/${f}`)] as const);

function rule(css: string, selector: string): string {
  const m = css.match(new RegExp(`(?:^|[}/])\\s*${selector.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`));
  assert.ok(m, `${selector} rule missing`);
  return m[1];
}

describe("ask panel stacking", () => {
  it("sits above every z-index in shell.css", () => {
    const shell = [...read("app/shell.css").matchAll(/z-index:\s*(\d+)/g)].map((m) => Number(m[1]));
    const z = Number(rule(read("ask/ask.css"), ".ink-ask").match(/z-index:\s*(\d+)/)?.[1]);
    assert.ok(shell.length > 0);
    assert.ok(z > Math.max(...shell), `ink-ask z-index ${z} must exceed ${Math.max(...shell)}`);
  });
  it("escapes the canvas stacking context through a portal", () => {
    const tsx = read("ask/AskPanel.tsx");
    assert.ok(tsx.includes("createPortal"));
    assert.ok(tsx.includes(".ink-shell"));
    assert.ok(!tsx.includes("position: fixed"));
  });
  it("is absolutely placed under the top bar so the canvas does not resize", () => {
    const body = rule(read("ask/ask.css"), ".ink-ask");
    assert.match(body, /position:\s*absolute/);
    assert.match(body, /top:\s*var\(--component-top-bar-height\)/);
    assert.match(body, /right:\s*0/);
    assert.match(body, /bottom:\s*0/);
  });
});

describe("ask panel colour and controls", () => {
  it("has no lime, no hex and no raw button", () => {
    for (const [name, src] of askFiles()) {
      assert.ok(!/lime/i.test(src), `${name} names lime`);
      assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(src), `${name} holds hex`);
      assert.ok(!src.includes("<button"), `${name} uses a raw <button`);
    }
  });
});
