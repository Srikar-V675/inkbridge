import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { configureExcalidraw, initialAppState } from "../src/lib/excalidrawEnv.ts";

describe("configureExcalidraw", () => {
  it("turns on render throttling", () => {
    const w: Record<string, unknown> = {};
    configureExcalidraw(w, "/");
    assert.equal(w.EXCALIDRAW_THROTTLE_RENDER, true);
  });
  it("points the asset path at the copied fonts under the Vite base", () => {
    const w: Record<string, unknown> = {};
    configureExcalidraw(w, "/");
    assert.equal(w.EXCALIDRAW_ASSET_PATH, "/excalidraw-assets/");
    configureExcalidraw(w, "/ink/");
    assert.equal(w.EXCALIDRAW_ASSET_PATH, "/ink/excalidraw-assets/");
  });
});

describe("initialAppState", () => {
  it("is pen mode even with no remembered view", () => {
    assert.deepEqual(initialAppState(null), { penMode: true });
  });
  it("keeps the remembered view next to pen mode", () => {
    const a = initialAppState({ scrollX: 5, scrollY: -7, zoom: 1.5 }) as Record<string, unknown>;
    assert.equal(a.penMode, true);
    assert.deepEqual([a.scrollX, a.scrollY, a.zoom], [5, -7, { value: 1.5 }]);
  });
  it("never carries elements", () => {
    assert.ok(!("elements" in initialAppState(null)));
  });
});
