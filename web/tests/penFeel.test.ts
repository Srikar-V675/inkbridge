import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const web = new URL("../", import.meta.url);
const dist = "node_modules/@excalidraw/excalidraw/dist/";
const devPath = new URL(dist + "dev/chunk-4FTI6OG3.js", web);
const prodPath = new URL(dist + "prod/chunk-K2UTITRG.js", web);
const patchPath = new URL("patches/@excalidraw+excalidraw+0.18.1.patch", web);

function read(url: URL): string {
  assert.ok(existsSync(url), `missing ${url.pathname}: run npm ci in web/ (excalidraw 0.18.1 only)`);
  return readFileSync(url, "utf8");
}

function devSlice(): string {
  const src = read(devPath);
  const start = src.indexOf("function getFreeDrawSvgPath");
  assert.ok(start >= 0, "getFreeDrawSvgPath not found in dev chunk");
  const end = src.indexOf("return getSvgPathFromStroke", start);
  assert.ok(end > start, "end of getFreeDrawSvgPath not found in dev chunk");
  return src.slice(start, end);
}

test("prod chunk has patched freedraw constants", () => {
  const src = read(prodPath);
  assert.ok(src.includes("thinning:.3,smoothing:.5,streamline:.2"));
  assert.ok(!src.includes("thinning:.6"));
});

test("dev chunk has patched freedraw constants", () => {
  const s = devSlice();
  assert.ok(s.includes("thinning: 0.3,"));
  assert.ok(s.includes("streamline: 0.2,"));
  assert.ok(!s.includes("thinning: 0.6"));
});

test("pressure data flow is intact", () => {
  const s = devSlice();
  assert.ok(s.includes("element.pressures[i]"));
  assert.ok(s.includes("simulatePressure: element.simulatePressure"));
  const p = read(prodPath);
  assert.ok(p.includes("e.pressures[i]"));
  assert.ok(p.includes("simulatePressure:e.simulatePressure"));
});

// The pen-feel hunks (the two chunk files) change only these numbers; the index.js hunks are the
// INK-181 sample hook, pinned by the last test in this file.
test("patch only changes the thinning and streamline numbers in the freedraw chunks", () => {
  const files = read(patchPath).split(/^diff --git /m).filter((f) => /dist\/(dev|prod)\/chunk-/.test(f.split("\n")[0]));
  assert.equal(files.length, 2, "pen-feel hunks for the dev and prod chunk");
  const lines = files.join("\n").split("\n");
  const norm = (l: string) =>
    l
      .slice(1)
      .replace(/thinning:\s*0?\.\d+/g, "thinning:N")
      .replace(/streamline:\s*0?\.\d+/g, "streamline:N");
  const removed: string[] = [];
  const added: string[] = [];
  for (const l of lines) {
    if (l.startsWith("---") || l.startsWith("+++")) continue;
    if (l.startsWith("-")) removed.push(norm(l));
    else if (l.startsWith("+")) added.push(norm(l));
  }
  assert.ok(removed.length > 0);
  assert.deepEqual(removed, added);
});

test("package.json wires patch-package", () => {
  const pkg = JSON.parse(read(new URL("package.json", web)));
  assert.equal(pkg.scripts.postinstall, "patch-package");
  assert.ok(pkg.devDependencies["patch-package"]);
});

// INK-181 (decision 0076): the freedraw move and pointerup handlers take every collected pen sample
// through globalThis.__inkbridgePenSamples, falling back to their own event when it is absent.
test("both builds drain the pen sample hook in freedraw move and pointerup", () => {
  const dev = read(new URL(dist + "dev/index.js", web));
  assert.ok(dev.includes("for (const sample of globalThis.__inkbridgePenSamples?.(event) ?? [event])"));
  assert.ok(dev.includes("for (const sample of globalThis.__inkbridgePenSamples?.(childEvent) ?? [])"));
  const prod = read(new URL(dist + "prod/index.js", web));
  assert.ok(prod.includes("globalThis.__inkbridgePenSamples?.(r)??[r]"));
  assert.ok(prod.includes("globalThis.__inkbridgePenSamples?.(r)??[]"));
  const patch = read(patchPath);
  assert.ok(patch.includes("__inkbridgePenSamples"), "the patch file must carry the sample hook, or npm ci drops it");
});
