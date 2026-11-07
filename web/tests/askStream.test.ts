import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { applyQuestionDelta, applyQuestionUpdate, isStreaming, type Question } from "../src/ask/ask.ts";
import { AnswerMarkdown } from "../src/ask/askMarkdown.ts";

const q = (over: Partial<Question> = {}): Question => ({
  id: "a", document_id: "c", parent_id: null, text: "t", focus_element_ids: [], focus_chunk_ids: [],
  status: "pending", answer_md: null, canvas_text: null, sources: [], created_at: "",
  runner_status: "running", runner_error: null, partial_answer: null, partial_seq: 0, ...over,
});

describe("applyQuestionDelta", () => {
  it("appends the next seq, treating null as empty", () => {
    const r = applyQuestionDelta([q()], { id: "a", seq: 1, text: "he" });
    assert.equal(r.gap, false);
    assert.deepEqual([r.list[0].partial_answer, r.list[0].partial_seq], ["he", 1]);
    const r2 = applyQuestionDelta(r.list, { id: "a", seq: 2, text: "llo" });
    assert.equal(r2.list[0].partial_answer, "hello");
  });
  it("ignores a duplicate", () => {
    const list = [q({ partial_answer: "he", partial_seq: 1 })];
    const r = applyQuestionDelta(list, { id: "a", seq: 1, text: "he" });
    assert.equal(r.list, list);
    assert.equal(r.gap, false);
  });
  it("reports a gap and leaves the list alone", () => {
    const list = [q({ partial_answer: "he", partial_seq: 1 })];
    const r = applyQuestionDelta(list, { id: "a", seq: 3, text: "x" });
    assert.equal(r.list, list);
    assert.equal(r.gap, true);
  });
  it("reports a gap for an unknown or non-pending question", () => {
    assert.equal(applyQuestionDelta([q()], { id: "zz", seq: 1, text: "x" }).gap, true);
    assert.equal(applyQuestionDelta([q({ status: "answered" })], { id: "a", seq: 1, text: "x" }).gap, true);
  });
});

describe("question update and streaming state", () => {
  it("update replaces the partial fields", () => {
    const list = applyQuestionUpdate([q({ partial_answer: "he", partial_seq: 1 })], q());
    assert.deepEqual([list[0].partial_answer, list[0].partial_seq], [null, 0]);
  });
  it("isStreaming needs a pending question with text", () => {
    assert.equal(isStreaming(q({ partial_answer: "x" })), true);
    assert.equal(isStreaming(q({ partial_answer: "" })), false);
    assert.equal(isStreaming(q({ partial_answer: "x", status: "answered" })), false);
  });
});

describe("partial markdown", () => {
  const render = (s: string) => renderToStaticMarkup(h(AnswerMarkdown, { source: s }));
  it("renders an unclosed fence", () => {
    assert.ok(render("Here:\n```js\nconst a = 1").includes("const a = 1"));
  });
  it("shows no half-open tag", () => {
    const o = render("see <scr");
    assert.ok(!o.includes("<scr") && !o.includes("<script"));
  });
  it("drops an unsafe half link", () => {
    assert.ok(!render("[x](http://ev").includes("href"));
    assert.ok(!render("[x](javascript:alert(1)").includes("href"));
  });
});
