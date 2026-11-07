import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Question } from "../src/ask/ask.ts";
import {
  canSend, groupThreads, messageCount, relativeTime, replyTarget, scopeLine, threadLine, threadOfQuestion,
  threadTitle, threadsWithDraft,
} from "../src/ask/threads.ts";

const q = (over: Partial<Question> = {}): Question => ({
  id: "abc123", document_id: "c", parent_id: null, text: "t", focus_element_ids: [], focus_chunk_ids: [],
  status: "answered", answer_md: "Hello **world**", canvas_text: null, sources: [], created_at: "",
  runner_status: "pending", runner_error: null, ...over,
});

describe("groupThreads", () => {
  it("joins a follow-up to its root and keeps two roots apart", () => {
    const ts = groupThreads([q({ id: "a" }), q({ id: "b" }), q({ id: "a2", parent_id: "a" })]);
    assert.equal(ts.length, 2);
    assert.deepEqual(ts.find((t) => t.id === "a")!.items.map((x) => x.id), ["a", "a2"]);
    assert.deepEqual(ts.find((t) => t.id === "b")!.items.map((x) => x.id), ["b"]);
  });
  it("orders by newest activity and oldest first inside", () => {
    const ts = groupThreads([q({ id: "a" }), q({ id: "b" }), q({ id: "a2", parent_id: "a" }), q({ id: "a3", parent_id: "a2" })]);
    assert.deepEqual(ts.map((t) => t.id), ["a", "b"]);
    assert.deepEqual(ts[0].items.map((x) => x.id), ["a", "a2", "a3"]);
    const ts2 = groupThreads([q({ id: "a" }), q({ id: "a2", parent_id: "a" }), q({ id: "b" })]);
    assert.deepEqual(ts2.map((t) => t.id), ["b", "a"]);
  });
  it("makes an orphaned follow-up its own root", () => {
    const ts = groupThreads([q({ id: "x", parent_id: "missing" })]);
    assert.deepEqual(ts.map((t) => t.id), ["x"]);
  });
  it("terminates on a parent cycle", () => {
    const ts = groupThreads([q({ id: "a", parent_id: "b" }), q({ id: "b", parent_id: "a" })]);
    assert.ok(ts.length >= 1 && ts.length <= 2);
  });
});

describe("thread helpers", () => {
  it("replyTarget is the last item, title the first", () => {
    const [t] = groupThreads([q({ id: "a", text: "first" }), q({ id: "a2", parent_id: "a", text: "second" })]);
    assert.equal(replyTarget(t).id, "a2");
    assert.equal(threadTitle(t), "first");
  });
  it("messageCount adds answered replies to questions", () => {
    const [t] = groupThreads([q({ id: "a" }), q({ id: "a2", parent_id: "a", status: "pending" })]);
    assert.equal(messageCount(t), 3);
  });
});

describe("threadLine", () => {
  const one = (over: Partial<Question>) => threadLine(groupThreads([q(over)])[0]);
  it("shows a failed runner", () => {
    assert.deepEqual(one({ status: "pending", runner_status: "failed", runner_error: "boom" }), { text: "The answering agent failed: boom", failed: true });
  });
  it("waits, cancels, answers", () => {
    assert.deepEqual(one({ status: "pending" }), { text: "Waiting for an agent", failed: false });
    assert.deepEqual(one({ status: "cancelled" }), { text: "Cancelled", failed: false });
    assert.equal(one({ answer_md: "## Hi\n\nBody" }).text, "Hi");
  });
  it("drops hostile urls", () => {
    const t = one({ answer_md: "[x](javascript:alert(1))" }).text;
    assert.ok(!t.includes("javascript"));
    assert.ok(t.startsWith("x"));
  });
  it("reads the latest question of the thread", () => {
    const ts = groupThreads([q({ id: "a", answer_md: "old" }), q({ id: "a2", parent_id: "a", status: "cancelled" })]);
    assert.equal(threadLine(ts[0]).text, "Cancelled");
  });
});

describe("relativeTime", () => {
  const now = new Date(2026, 10, 6, 12, 0).getTime();
  const iso = (ms: number) => new Date(ms).toISOString();
  it("buckets", () => {
    assert.equal(relativeTime(iso(now - 20_000), now), "Just now");
    assert.equal(relativeTime(iso(now - 12 * 60_000), now), "12 min ago");
    assert.equal(relativeTime(iso(new Date(2026, 10, 6, 9, 0).getTime()), now), "3 h ago");
    assert.equal(relativeTime(iso(new Date(2026, 10, 5, 23, 0).getTime()), now), "Yesterday");
    assert.equal(relativeTime(iso(new Date(2026, 10, 3, 10, 0).getTime()), now), "3 Nov");
    assert.equal(relativeTime("nope", now), "");
  });
});

describe("canSend", () => {
  it("needs a selection in the list view only", () => {
    assert.equal(canSend({ text: "x", busy: false, selected: 0, followUp: false }), false);
    assert.equal(canSend({ text: "x", busy: false, selected: 2, followUp: false }), true);
    assert.equal(canSend({ text: "x", busy: false, selected: 0, followUp: true }), true);
    assert.equal(canSend({ text: "x", busy: true, selected: 2, followUp: true }), false);
    assert.equal(canSend({ text: "   ", busy: false, selected: 2, followUp: true }), false);
  });
});

describe("scopeLine", () => {
  it("counts", () => {
    assert.equal(scopeLine(0, 0), "Nothing selected yet");
    assert.equal(scopeLine(1, 1), "About 1 selected element");
    assert.equal(scopeLine(3, 3), "About 3 selected elements");
    assert.equal(scopeLine(200, 250), "About 200 selected elements, capped at 200");
  });
});

describe("draft links", () => {
  const ts = groupThreads([q({ id: "a" }), q({ id: "b" }), q({ id: "a2", parent_id: "a" })]);
  it("threadOfQuestion returns the root, also for a follow-up", () => {
    assert.equal(threadOfQuestion(ts, "a2"), "a");
    assert.equal(threadOfQuestion(ts, "b"), "b");
    assert.equal(threadOfQuestion(ts, "zz"), null);
  });
  it("threadsWithDraft marks the thread holding the question", () => {
    assert.deepEqual([...threadsWithDraft(ts, [{ payload: { question_id: "a2" } }])], ["a"]);
    assert.equal(threadsWithDraft(ts, [{ payload: {} }, { payload: { question_id: null } }]).size, 0);
  });
});
