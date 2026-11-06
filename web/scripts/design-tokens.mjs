import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const web = new URL("../", import.meta.url);
const DESIGN = new URL("../DESIGN.md", web); // repo root
const OUT = new URL("src/styles/tokens.css", web);
export const POPOVER_SHADOW = "0 10px 28px rgba(46, 45, 43, 0.16)"; // prose-only in DESIGN.md (Elevation & Depth)

const GROUPS = { colors: "color", rounded: "radius", spacing: "space" };
const TYPE_PROPS = { fontFamily: "family", fontSize: "size", fontWeight: "weight", lineHeight: "line-height", letterSpacing: "tracking" };
const kebab = (s) => s.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());

/** Indentation-based reader for DESIGN.md front matter: `key:` opens a map, `key: value` is a leaf. */
export function parseFrontMatter(md) {
  const m = /^---\n([\s\S]*?)\n---/.exec(md);
  if (!m) throw new Error("DESIGN.md has no front matter");
  const root = {};
  const stack = [{ indent: -1, node: root }];
  for (const raw of m[1].split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const indent = raw.length - raw.trimStart().length;
    const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (!kv) throw new Error(`unsupported front matter line: ${raw}`);
    while (stack[stack.length - 1].indent >= indent) stack.pop();
    const parent = stack[stack.length - 1].node;
    if (kv[2] === "") {
      parent[kv[1]] = {};
      stack.push({ indent, node: parent[kv[1]] });
    } else parent[kv[1]] = kv[2].replace(/^"(.*)"$/, "$1");
  }
  return root;
}

/** `{colors.charcoal}` -> `var(--color-charcoal)`; `{typography.x}` -> null (skipped); anything else as written. */
function resolve(value) {
  const r = /^\{(\w+)\.([\w-]+)\}$/.exec(value);
  if (!r) return value;
  return GROUPS[r[1]] ? `var(--${GROUPS[r[1]]}-${r[2]})` : null;
}

export function buildTokensCss(md) {
  const fm = parseFrontMatter(md);
  const out = [];
  for (const [group, prefix] of Object.entries(GROUPS))
    for (const [name, value] of Object.entries(fm[group] ?? {})) out.push(`  --${prefix}-${name}: ${value};`);
  for (const [name, props] of Object.entries(fm.typography ?? {}))
    for (const [prop, value] of Object.entries(props))
      out.push(`  --type-${name}-${TYPE_PROPS[prop]}: ${prop === "fontFamily" ? `"${value}", ${value === "Caveat" ? "cursive" : "system-ui, sans-serif"}` : value};`);
  for (const [name, props] of Object.entries(fm.components ?? {}))
    for (const [prop, value] of Object.entries(props)) {
      const v = resolve(value);
      if (v !== null) out.push(`  --component-${name}-${kebab(prop)}: ${v};`);
    }
  out.push(`  --shadow-popover: ${POPOVER_SHADOW};`);
  return `/* Generated from DESIGN.md by web/scripts/design-tokens.mjs (npm run tokens). Do not edit. */\n:root {\n${out.join("\n")}\n}\n`;
}

if (process.argv[1] === fileURLToPath(import.meta.url))
  writeFileSync(OUT, buildTokensCss(readFileSync(DESIGN, "utf8")));
