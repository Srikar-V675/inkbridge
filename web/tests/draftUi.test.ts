import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { draftCard, failureText, jumpTarget, trayLabel, verdictToast } from "../src/drafts/draftUi.ts";
import { NOT_READY } from "../src/drafts/resolve.ts";
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
  it("groups not-ready and dedupes other messages", () => {
    const failed = [
      { opId: "a", message: NOT_READY },
      { opId: "b", message: NOT_READY },
      { opId: "c", message: "could not save" },
      { opId: "d", message: "could not save" },
    ];
    assert.equal(failureText({ done: [], retry: [], failed }), "2 not ready; could not save");
    assert.equal(failureText({ done: [], retry: [], failed: [] }), "");
  });
});

describe("jumpTarget", () => {
  it("prefers the oldest unseen draft, else the first draft", () => {
    assert.equal(jumpTarget(["u1", "u2"], [{ opId: "d1" }]), "u1");
    assert.equal(jumpTarget([], [{ opId: "d1" }, { opId: "d2" }]), "d1");
    assert.equal(jumpTarget([], []), null);
  });
});

describe("draftCard", () => {
  const tag = (opId: string) => ({ draft: true, op_id: opId });
  it("text drafts get a one-line preview", () => {
    const els = [el({ id: "o1:1", type: "text", text: "A large α\nmakes steps  overshoot", customData: tag("o1") })];
    assert.deepEqual(draftCard(els, "o1"), { kind: "text", preview: "A large α makes steps overshoot" });
  });
  it("a diagram has no preview", () => {
    const els = [
      el({ id: "o2:1", type: "rectangle", customData: tag("o2") }),
      el({ id: "o2:2", type: "text", text: "node", customData: tag("o2") }),
    ];
    assert.deepEqual(draftCard(els, "o2"), { kind: "diagram", preview: "" });
  });
  it("ignores an element that copies the tag without the op id prefix", () => {
    const els = [
      el({ id: "o1:1", type: "text", text: "real", customData: tag("o1") }),
      el({ id: "zzz", type: "text", text: "STOLEN", customData: tag("o1") }),
    ];
    assert.ok(!draftCard(els, "o1").preview.includes("STOLEN"));
  });
  it("ignores deleted elements", () => {
    const els = [
      el({ id: "o1:1", type: "text", text: "kept", customData: tag("o1") }),
      el({ id: "o1:2", type: "text", text: "gone", isDeleted: true, customData: tag("o1") }),
    ];
    assert.equal(draftCard(els, "o1").preview, "kept");
  });
  it("truncates long previews with an ellipsis", () => {
    const els = [el({ id: "o1:1", type: "text", text: "word ".repeat(100), customData: tag("o1") })];
    const { preview } = draftCard(els, "o1");
    assert.ok(preview.endsWith("…"));
    assert.ok(preview.length <= 200);
  });
});
