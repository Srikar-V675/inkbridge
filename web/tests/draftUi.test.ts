import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { draftCard, failureText, jumpTarget, trayLabel, verdictToast } from "../src/drafts/draftUi.ts";
import type { DraftElement } from "../src/drafts/drafts.ts";

const el = (o: Record<string, unknown>) => o as unknown as DraftElement;

describe("trayLabel", () => {
  it("pluralises", () => {
    assert.equal(trayLabel(1), "1 draft on this canvas");
    assert.equal(trayLabel(3), "3 drafts on this canvas");
  });
});

describe("verdictToast", () => {
  it("accepted and rejected wording", () => {
    assert.equal(verdictToast("accepted", { done: ["a"] }), "Added to your canvas");
    assert.equal(verdictToast("accepted", { done: ["a", "b"] }), "Added 2 drafts to your canvas");
    assert.equal(verdictToast("rejected", { done: ["a"] }), "Draft removed.");
    assert.equal(verdictToast("rejected", { done: ["a", "b"] }), "2 drafts removed.");
  });
  it("a failed verdict does not toast success", () => {
    assert.equal(verdictToast("accepted", { done: [] }), null);
    assert.equal(verdictToast("rejected", { done: [] }), null);
  });
});

describe("failureText", () => {
  it("dedupes the failed messages", () => {
    const r = [{ ok: false as const, message: "x" }, { ok: false as const, message: "x" }, { ok: true as const, op: null }, { ok: false as const, message: "y" }];
    assert.equal(failureText(r), "x; y");
    assert.equal(failureText([]), "");
  });
});

describe("jumpTarget", () => {
  it("prefers the oldest unseen draft, else the first draft", () => {
    assert.equal(jumpTarget(["u1", "u2"], [{ opId: "d1" }]), "u1");
    assert.equal(jumpTarget([], [{ opId: "d1" }, { opId: "d2" }]), "d1");
    assert.equal(jumpTarget([], []), null);
  });
  it("skips a draft that has no box and falls back to the next one that has", () => {
    const hasBox = (id: string) => id !== "u1";
    assert.equal(jumpTarget(["u1"], [{ opId: "d1" }], hasBox), "d1");
    assert.equal(jumpTarget(["u1", "u2"], [{ opId: "d1" }], hasBox), "u2");
    assert.equal(jumpTarget(["u1"], [{ opId: "u1" }], hasBox), null);
  });
});

describe("draftCard", () => {
  it("text drafts get a one-line preview", () => {
    const op = { elements: [el({ id: "o1:1", type: "text", text: "A large α\nmakes steps  overshoot" })] };
    assert.deepEqual(draftCard(op), { kind: "text", preview: "A large α makes steps overshoot" });
  });
  it("a diagram has no preview", () => {
    const op = { elements: [el({ id: "o2:1", type: "rectangle" }), el({ id: "o2:2", type: "text", text: "node" })] };
    assert.deepEqual(draftCard(op), { kind: "diagram", preview: "" });
  });
  it("truncates long previews with an ellipsis", () => {
    const { preview } = draftCard({ elements: [el({ id: "o1:1", type: "text", text: "word ".repeat(100) })] });
    assert.ok(preview.endsWith("…"));
    assert.ok(preview.length <= 200);
  });
});
