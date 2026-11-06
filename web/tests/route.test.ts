import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { canvasKey, parseLocation, readRoute } from "../src/lib/route.ts";

describe("parseLocation", () => {
  it("is home without a canvas parameter", () => {
    assert.deepEqual(parseLocation(""), { kind: "home", archived: false });
    assert.deepEqual(parseLocation("?chunk=c1"), { kind: "home", archived: false });
    assert.deepEqual(parseLocation("?canvas="), { kind: "home", archived: false });
  });
  it("reads the archived view from ?view=archived", () => {
    assert.deepEqual(parseLocation("?view=archived"), { kind: "home", archived: true });
    assert.deepEqual(parseLocation("?view=x"), { kind: "home", archived: false });
    assert.deepEqual(parseLocation("?canvas=a&view=archived"), { kind: "canvas", canvas: "a", chunk: null });
  });
  it("is a canvas with its chunk", () => {
    assert.deepEqual(parseLocation("?canvas=abc"), { kind: "canvas", canvas: "abc", chunk: null });
    assert.deepEqual(parseLocation("?canvas=abc&chunk=c1"), { kind: "canvas", canvas: "abc", chunk: "c1" });
  });
});

describe("canvasKey", () => {
  const loc = (canvas: string, chunk: string | null) => ({ kind: "canvas" as const, canvas, chunk });
  it("remounts for another canvas or another chunk, not for the same link", () => {
    assert.notEqual(canvasKey(loc("a", null)), canvasKey(loc("b", null)));
    assert.equal(canvasKey(loc("a", "c1")), canvasKey(loc("a", "c1")));
    assert.notEqual(canvasKey(loc("a", "c1")), canvasKey(loc("a", "c2")));
    assert.notEqual(canvasKey(loc("a", null)), canvasKey(loc("a", "c1")));
  });
});

describe("readRoute", () => {
  it("still defaults to the default canvas", () => {
    assert.deepEqual(readRoute(""), { canvas: "default", chunk: null });
  });
});
