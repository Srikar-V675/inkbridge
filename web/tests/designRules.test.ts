import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const ROOT = fileURLToPath(new URL("../", import.meta.url));

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return walk(p);
    return /\.(ts|tsx|css)$/.test(name) ? [p] : [];
  });
}

/** All source files under web/src as { relative path: text }. */
function sources(): Record<string, string> {
  return Object.fromEntries(walk(SRC).map((p) => [relative(SRC, p), readFileSync(p, "utf8")]));
}

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/;
// Pre-v4 surfaces that still hold inline hex; later screen tickets rebuild them. The list can only shrink.
const LEGACY = ["app/App.tsx", "ask/AskPanel.tsx", "chunks/ChunkOverlay.tsx", "drafts/DraftBar.tsx"];

/** Files (relative to src) that name a hex colour, except tokens.css. */
function hexOffenders(files: Record<string, string>): string[] {
  return Object.entries(files)
    .filter(([name, text]) => name !== "styles/tokens.css" && HEX.test(text))
    .map(([name]) => name)
    .sort();
}

describe("no hex colour outside tokens.css", () => {
  it("only the LEGACY files hold hex", () => {
    assert.deepEqual(hexOffenders(sources()), [...LEGACY].sort());
  });

  it("every LEGACY file still holds hex", () => {
    const files = sources();
    for (const name of LEGACY) assert.ok(HEX.test(files[name] ?? ""), `remove ${name} from LEGACY`);
  });

  it("the checker flags a new file", () => {
    assert.deepEqual(hexOffenders({ "ui/New.css": "a{color:#fff}", "ui/Ok.css": "a{color:var(--color-paper)}" }), ["ui/New.css"]);
    assert.deepEqual(hexOffenders({ "ask/AskPanel.tsx": "<b>#{n}</b>" }), []);
  });
});

describe("Instrument Sans is local", () => {
  it("ships the woff2 and references it relatively", () => {
    const woff = join(SRC, "styles/fonts/InstrumentSans-latin.woff2");
    assert.ok(existsSync(woff));
    assert.equal(readFileSync(woff).subarray(0, 4).toString("latin1"), "wOF2");
    const css = readFileSync(join(SRC, "styles/fonts.css"), "utf8");
    assert.ok(css.includes("InstrumentSans-latin.woff2"));
    assert.ok(!css.includes("http"));
  });

  it("nothing asks Google for fonts", () => {
    const files = { ...sources(), "index.html": readFileSync(join(ROOT, "index.html"), "utf8") };
    for (const [name, text] of Object.entries(files)) {
      assert.ok(!text.includes("fonts.googleapis.com"), name);
      assert.ok(!text.includes("fonts.gstatic.com"), name);
    }
  });
});

describe("index.css", () => {
  it("imports tokens first", () => {
    assert.match(readFileSync(join(SRC, "index.css"), "utf8"), /^@import "\.\/styles\/tokens\.css";/);
  });
});
