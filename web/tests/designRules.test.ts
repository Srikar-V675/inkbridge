import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { parseTokenCss, resolveVar } from "../src/ui/tokenTable.ts";

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
const LEGACY = ["app/App.tsx"];

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

const tokens = parseTokenCss(readFileSync(join(SRC, "styles/tokens.css"), "utf8"));

/** { selector: { property: value } } for the simple rules of a stylesheet (no media queries or nesting). */
function rules(css: string): Record<string, Record<string, string>> {
  const out: Record<string, Record<string, string>> = {};
  for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const sel = m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim();
    const decls = (out[sel] ??= {});
    for (const d of m[2].split(";")) {
      const i = d.indexOf(":");
      if (i > 0) decls[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
  }
  return out;
}

const px = (value: string | undefined): number => {
  const m = /^(-?[\d.]+)px$/.exec(resolveVar(tokens, value ?? ""));
  return m ? Number(m[1]) : NaN;
};

const uiFiles = (ext: string): [string, string][] =>
  Object.entries(sources()).filter(([n]) => n.startsWith("ui/") && n.endsWith(ext));

describe("interactive primitives", () => {
  // INK-177, decision 0083: the face scales with --ui-scale, an ::after box keeps the 44 px hit area.
  const FACE = "calc(var(--space-touch) * var(--ui-scale, 1))";
  const HIT_INSET = "min(0px, calc((var(--ui-scale, 1) - 1) * var(--space-touch) / 2))";

  it("buttons and icon buttons have a 44 px hit area at every UI size", () => {
    const all = Object.assign({}, ...uiFiles(".css").map(([, text]) => rules(text)));
    assert.equal(px("var(--space-touch)"), 44);
    const icon = all[".ink-icon-button"];
    assert.ok(icon, ".ink-icon-button");
    for (const p of ["width", "min-width", "min-height"]) assert.equal(icon[p], FACE, `icon ${p}`);
    assert.equal(icon["position"], "relative");
    const iconAfter = all[".ink-icon-button::after"];
    assert.ok(iconAfter, "icon ::after");
    assert.equal(iconAfter["content"], '""');
    assert.equal(iconAfter["position"], "absolute");
    assert.equal(iconAfter["inset"], HIT_INSET);

    const button = all[".ink-button"];
    assert.ok(button, ".ink-button");
    assert.equal(button["min-height"], FACE);
    assert.equal(button["position"], "relative");
    const buttonAfter = all[".ink-button::after"];
    assert.ok(buttonAfter, "button ::after");
    assert.equal(buttonAfter["content"], '""');
    assert.equal(buttonAfter["position"], "absolute");
    assert.equal(buttonAfter["inset"], `${HIT_INSET} 0`);
  });

  it("the hit area formula gives at least 44 px for every scale", () => {
    for (const s of [0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2]) {
      const visual = 44 * s;
      const hit = visual + 2 * -Math.min(0, ((s - 1) * 44) / 2);
      assert.ok(hit >= 44 - 1e-9, `scale ${s}: ${hit}`);
    }
  });

  it("the chip is the one 36 px target", () => {
    const all = Object.assign({}, ...uiFiles(".css").map(([, text]) => rules(text)));
    assert.equal(all[".ink-chip"]["height"], "var(--component-offer-chip-height)");
    assert.equal(px(all[".ink-chip"]["height"]), 36);
  });

  it("only Button, IconButton, Chip and Kit render a raw button", () => {
    for (const [name, text] of uiFiles(".tsx")) {
      if (/^ui\/(Button|IconButton|Chip|Kit)\.tsx$/.test(name)) continue;
      assert.ok(!text.includes("<button"), `${name} must compose Button or IconButton`);
    }
  });
});

const hasToken = (text: string, names: string[]) => names.some((n) => text.includes(`var(${n})`));

/** Files (except tokens.css) that use a lime variable, minus the allowed ones. */
function limeOffenders(files: Record<string, string>, names: string[], allowed: string[]): string[] {
  return Object.entries(files)
    .filter(([n, text]) => n !== "styles/tokens.css" && !allowed.includes(n) && (names.some((x) => text.includes(x)) || /lime/i.test(text)))
    .map(([n]) => n)
    .sort();
}

describe("lime is the agent", () => {
  const limeNames = [
    "--color-lime",
    ...tokens.filter((t) => t.name !== "--color-lime" && resolveVar(tokens, t.value).toUpperCase() === "#D4F23A").map((t) => t.name),
  ];

  it("the lime variables are found", () => {
    assert.ok(limeNames.includes("--component-offer-chip-background-color"));
    assert.ok(limeNames.includes("--component-draft-badge-background-color"));
    assert.ok(limeNames.includes("--component-working-dot-background-color")); // INK-198
  });

  it("appears only in Chip.css and Badge.css", () => {
    const files = sources();
    assert.deepEqual(limeOffenders(files, limeNames, ["ui/Chip.css", "ui/Badge.css", "app/WorkingDot.css"]), []);
    assert.ok(hasToken(files["ui/Chip.css"], limeNames), "Chip uses lime");
    assert.ok(hasToken(files["ui/Badge.css"], limeNames), "Badge uses lime");
    assert.ok(hasToken(files["app/WorkingDot.css"], limeNames), "WorkingDot uses lime");
  });

  it("the checker flags a stray use", () => {
    assert.deepEqual(limeOffenders({ "ui/Button.css": "x{background:var(--color-lime)}" }, limeNames, []), ["ui/Button.css"]);
  });
});

describe("flat design", () => {
  it("no shadow or gradient outside Toast", () => {
    for (const [name, text] of uiFiles(".css")) {
      if (name === "ui/Toast.css") {
        assert.ok(text.includes("var(--shadow-popover)"));
        continue;
      }
      assert.ok(!/box-shadow|gradient\(/.test(text), name);
    }
  });
});
