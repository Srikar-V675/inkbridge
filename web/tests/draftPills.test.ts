import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { cardOpIds, pillPosition, showBulk } from "../src/drafts/draftPills.ts";

const v = { scrollX: 0, scrollY: 0, zoom: 1, width: 1280, height: 800 };
const size = { width: 220, height: 52 };
const ins = { top: 72, right: 8, bottom: 88, left: 80 };
const box = { x: 300, y: 300, width: 200, height: 100 };

describe("pillPosition", () => {
  it("anchors above the top-right corner", () => {
    assert.deepEqual(pillPosition(box, v, size, 6, ins), { left: 280, top: 242 });
  });
  it("follows zoom and scroll", () => {
    const p = pillPosition(box, { ...v, zoom: 2, scrollX: -100 }, size, 6, ins);
    assert.equal(p?.left, 580);
  });
  it("flips below when there is no room above", () => {
    const p = pillPosition({ ...box, y: 80 }, v, size, 6, ins);
    assert.equal(p?.top, 80 + 100 + 6);
  });
  it("clamps to the left inset and the bottom inset", () => {
    const l = pillPosition({ x: 0, y: 300, width: 100, height: 100 }, v, size, 6, ins);
    assert.equal(l?.left, 80);
    const b = pillPosition({ x: 300, y: 80, width: 200, height: 700 }, v, size, 6, ins);
    assert.equal(b?.top, 800 - 88 - 52);
  });
  it("returns null for an off-screen draft", () => {
    assert.equal(pillPosition({ x: 5000, y: 5000, width: 10, height: 10 }, v, size, 6, ins), null);
  });
  it("gives two drafts side by side different positions", () => {
    const a = pillPosition(box, v, size, 6, ins);
    const b = pillPosition({ ...box, x: 700 }, v, size, 6, ins);
    assert.notDeepEqual(a, b);
  });
});

describe("cardOpIds", () => {
  it("shows no card when nothing is selected", () => {
    assert.equal(cardOpIds([], ["a", "b"]).size, 0);
  });
  it("keeps only selected drafts that are visible", () => {
    assert.deepEqual([...cardOpIds(["a", "z"], ["a", "b"])], ["a"]);
  });
});

describe("showBulk", () => {
  it("is for two or more drafts", () => {
    assert.equal(showBulk(1), false);
    assert.equal(showBulk(2), true);
  });
});
