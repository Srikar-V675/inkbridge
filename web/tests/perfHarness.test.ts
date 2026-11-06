import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { budgetVerdict, ONCHANGE_BUDGET_MS, OFF_FLAGS, PATCHES, percentile, summarise, WRAP_PATTERNS } from "../scripts/perf/variants.ts";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const count = (text: string, find: string) => text.split(find).length - 1;

describe("percentile", () => {
  it("is nearest-rank", () => {
    assert.equal(percentile([1, 2, 3, 4, 100], 0.5), 3);
    assert.equal(percentile(Array.from({ length: 100 }, (_, i) => i + 1), 0.95), 95);
    assert.ok(Number.isNaN(percentile([], 0.5)));
  });
});

describe("summarise", () => {
  it("counts long tasks per run and onChange ms per move", () => {
    const s = summarise({ deltas: [16, 17, 33], longtasks: [60, 80], onChange: [1, 1, 2], moves: 4, runs: 2 });
    assert.equal(s.longPerRun, 1);
    assert.equal(s.onChangeMsPerMove, 1);
    assert.equal(s.p50, 17);
  });
  it("carries the no-effect count through", () => {
    const s = summarise({ deltas: [16], longtasks: [], onChange: [1], moves: 1, runs: 1, noEffect: 3 });
    assert.equal(s.noEffect, 3);
  });
});

describe("budgetVerdict", () => {
  const ok = { p50: 16, p95: 20, p99: 30, longPerRun: 0, onChangeMsPerMove: 0.5 };
  it("passes a build within 20 percent plus 2 ms of stock", () => {
    assert.equal(budgetVerdict({ built: { ...ok, p95: 26 }, stock: { ...ok, p95: 20 } }).ok, true);
  });
  it("fails on a slow p95", () => {
    const v = budgetVerdict({ built: { ...ok, p95: 27 }, stock: { ...ok, p95: 20 } });
    assert.equal(v.ok, false);
    assert.equal(v.reasons.length, 1);
  });
  it("fails on onChange cost over the budget", () => {
    const v = budgetVerdict({ built: { ...ok, onChangeMsPerMove: ONCHANGE_BUDGET_MS + 0.1 }, stock: ok });
    assert.equal(v.ok, false);
  });
  it("fails, never passes silently, on missing numbers (NaN compares false)", () => {
    for (const bad of [{ p95: NaN }, { onChangeMsPerMove: NaN }]) {
      const v = budgetVerdict({ built: { ...ok, ...bad }, stock: ok });
      assert.equal(v.ok, false, JSON.stringify(bad));
      assert.ok(v.reasons.length >= 1);
    }
    assert.equal(budgetVerdict({ built: ok, stock: { ...ok, p95: NaN } }).ok, false);
    assert.equal(budgetVerdict({ built: ok, stock: { ...ok, p95: Infinity } }).ok, false);
  });
  it("fails when a scenario had no effect (no stroke drawn, no pan)", () => {
    const v = budgetVerdict({ built: { ...ok, noEffect: 2 }, stock: ok });
    assert.equal(v.ok, false);
    assert.match(v.reasons.join(" "), /no effect/);
    assert.equal(budgetVerdict({ built: ok, stock: { ...ok, noEffect: 1 } }).ok, false);
    assert.equal(budgetVerdict({ built: { ...ok, noEffect: 0 }, stock: { ...ok, noEffect: 0 } }).ok, true);
  });
  it("keeps the budget small and finite", () => {
    assert.ok(Number.isFinite(ONCHANGE_BUDGET_MS) && ONCHANGE_BUDGET_MS > 0 && ONCHANGE_BUDGET_MS <= 5);
  });
});

describe("drift guard", () => {
  it("every patch finds its text exactly once in web/src", () => {
    for (const flag of OFF_FLAGS) {
      assert.ok(PATCHES[flag].length > 0, flag);
      for (const p of PATCHES[flag]) {
        const path = join(web, "src", p.file);
        assert.ok(existsSync(path), `${flag}: ${p.file} is gone`);
        assert.equal(count(readFileSync(path, "utf8"), p.find), 1, `${flag}: "${p.find}" in ${p.file}`);
      }
    }
  });
  it("App.tsx keeps the two strings the onChange timer replaces", () => {
    const app = readFileSync(join(web, "src/app/App.tsx"), "utf8");
    for (const w of WRAP_PATTERNS) assert.equal(count(app, w.find), 1, w.find);
  });
});
