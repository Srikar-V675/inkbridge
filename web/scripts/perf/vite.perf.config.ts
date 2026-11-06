// Vite config for the INK-174 bisect. The variant switches and the onChange timer are injected by
// the two plugins below, only here: vite.config.ts and the shipped build are untouched.
// One build serves every variant: flags come from the page URL (?off=dots,overlay).
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { OFF_FLAGS, PATCHES, WRAP_PATTERNS } from "./variants.ts";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const api = process.env.INKBRIDGE_API_URL ?? "http://127.0.0.1:8101";
const proxied = ["/documents", "/ops", "/regions", "/search", "/health", "/questions", "/debug"];
const proxy = { ...Object.fromEntries(proxied.map((p) => [p, api])), "/ws": { target: api, ws: true } };

const OFF = "\0virtual:perf-off";
const WRAP = "\0virtual:perf-wrap";

function perfOff(): Plugin {
  const byFile = new Map<string, { flag: string; find: string; replace: string }[]>();
  for (const flag of OFF_FLAGS) {
    for (const p of PATCHES[flag]) {
      const list = byFile.get(join(web, "src", p.file)) ?? [];
      list.push({ flag, find: p.find, replace: p.replace.replaceAll("{{OFF}}", flag) });
      byFile.set(join(web, "src", p.file), list);
    }
  }
  return {
    name: "perf-off",
    enforce: "pre",
    resolveId: (id) => (id === "virtual:perf-off" ? OFF : null),
    load: (id) =>
      id === OFF
        ? `export const __off = (flag) => (new URLSearchParams(location.search).get("off")?.split(",") ?? []).some((f) => f.split("+").includes(flag));`
        : null,
    transform(code, id) {
      const patches = byFile.get(id.split("?")[0]);
      if (!patches) return null;
      let out = code;
      for (const p of patches) {
        if (out.split(p.find).length !== 2) this.error(`perf patch for "${p.flag}": "${p.find}" is not in ${id} exactly once`);
        out = out.replace(p.find, () => p.replace);
      }
      return `import { __off } from "virtual:perf-off";\n${out}`;
    },
  };
}

function perfWrap(): Plugin {
  const app = join(web, "src/app/App.tsx");
  return {
    name: "perf-wrap",
    enforce: "pre",
    resolveId: (id) => (id === "virtual:perf-wrap" ? WRAP : null),
    load: (id) =>
      id === WRAP
        ? readFileSync(join(web, "scripts/perf/wrap.js"), "utf8")
        : null,
    transform(code, id) {
      if (id.split("?")[0] !== app) return null;
      let out = code;
      for (const w of WRAP_PATTERNS) {
        if (out.split(w.find).length !== 2) this.error(`perf wrap: "${w.find}" is not in App.tsx exactly once`);
        out = out.replace(w.find, () => w.replace);
      }
      return `import { perfApi, perfChange } from "virtual:perf-wrap";\n${out}`;
    },
  };
}

export default defineConfig({
  root: web,
  plugins: [react(), perfOff(), perfWrap()],
  server: { port: 5191, host: "127.0.0.1", proxy },
  preview: { port: 5191, host: "127.0.0.1", proxy },
  build: {
    rollupOptions: { input: { index: join(web, "index.html"), stock: join(web, "perf/stock.html") } },
    outDir: process.env.PERF_OUT ?? "/tmp/claude-1000/inkbridge-174/dist-perf",
    emptyOutDir: true,
  },
});
