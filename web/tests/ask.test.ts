import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  applyQuestionUpdate, diagramOp, fileName, mermaidBlock, noteUrl, focusIds, keepOnCanvas, keepOp, plainText, publishQuestion, runnerLine,
  subscribeQuestions, type Question,
} from "../src/ask/ask.ts";

const q = (over: Partial<Question> = {}): Question => ({
  id: "abc123", document_id: "c", parent_id: null, text: "t", focus_element_ids: [], focus_chunk_ids: [],
  status: "answered", answer_md: "Hello **world**", canvas_text: null, sources: [], created_at: "",
  runner_status: "pending", runner_error: null, partial_answer: null, partial_seq: 0, ...over,
});

describe("focusIds", () => {
  it("drops deleted, drafts, unselected and caps at 200", () => {
    const scene = [
      { id: "a" }, { id: "b", isDeleted: true }, { id: "c", customData: { draft: true } }, { id: "d" },
    ];
    assert.deepEqual(focusIds(scene, { a: true, b: true, c: true }), ["a"]);
    const many = Array.from({ length: 300 }, (_, i) => ({ id: `e${i}` }));
    const sel = Object.fromEntries(many.map((e) => [e.id, true]));
    assert.equal(focusIds(many, sel).length, 200);
  });
});

describe("fileName", () => {
  it("keeps only the last segment", () => {
    assert.equal(fileName("/home/x/vault/Notes/a.md"), "a.md");
    assert.equal(fileName("C:\\v\\Notes\\b.md"), "b.md");
    assert.equal(fileName(""), "note");
  });
});

describe("plainText", () => {
  it("removes hostile markup", () => {
    const t = plainText("[x](javascript:alert(1)) <img src=x onerror=alert(1)> ![p](http://evil/a.png) **b**");
    for (const bad of ["javascript", "onerror", "evil", "<img", "]("]) assert.ok(!t.includes(bad), bad);
    assert.ok(t.includes("b"));
  });
  it("keeps a lone < and comparisons", () => {
    assert.equal(plainText("a < b and c"), "a < b and c");
    assert.equal(plainText("x<5 and y>3"), "x<5 and y>3");
  });
  it("caps length", () => assert.equal(plainText("a".repeat(20000)).length, 2000));
});

describe("keepOp", () => {
  it("shape and idempotent id", () => {
    const op = keepOp(q(), null);
    assert.equal(op.op_id, "keep-abc123");
    assert.deepEqual(Object.keys(op.payload).sort(), ["question_id", "relation", "text"]);
    assert.deepEqual(Object.keys(keepOp(q(), "k1").payload).sort(), ["anchor", "question_id", "relation", "text"]);
    assert.equal(op.payload.question_id, "abc123");
    assert.equal(op.payload.relation, "answer");
  });
  it("uses canvas_text, stripped of markup, instead of the long answer", () => {
    assert.equal(keepOp(q({ canvas_text: "Short" }), null).payload.text, "Short");
    assert.equal(keepOp(q({ canvas_text: "**Bold** <b>x</b> [l](http://e)" }), null).payload.text, "Bold x l");
  });
  it("falls back to the first paragraph capped at 300", () => {
    const md = `${"a".repeat(400)}\n\nsecond`;
    assert.equal(keepOp(q({ answer_md: md }), null).payload.text, "a".repeat(300));
    assert.equal(keepOp(q({ answer_md: "one\n\ntwo" }), null).payload.text, "one");
  });
});

describe("diagram helpers", () => {
  it("mermaidBlock returns the first flowchart block", () => {
    const md = "x\n```mermaid\nsequenceDiagram\nA->>B: hi\n```\n```mermaid\nflowchart TD\n A-->B\n```";
    assert.equal(mermaidBlock(md), "flowchart TD\n A-->B");
    assert.equal(mermaidBlock("```mermaid\ngraph LR\nA-->B\n```"), "graph LR\nA-->B");
    assert.equal(mermaidBlock("no diagram"), null);
    assert.equal(mermaidBlock("```mermaid\nsequenceDiagram\nA->>B: hi\n```"), null);
  });
  it("diagramOp shape", () => {
    const op = diagramOp(q({ answer_md: "```mermaid\nflowchart TD\nA-->B\n```" }), "k1");
    assert.deepEqual(op, {
      type: "draw_diagram", op_id: "diagram-abc123",
      payload: { mermaid: "flowchart TD\nA-->B", question_id: "abc123", relation: "diagram", anchor: "k1" },
    });
    assert.equal("anchor" in diagramOp(q({ answer_md: "```mermaid\nflowchart TD\nA-->B\n```" }), null)!.payload, false);
    assert.equal(diagramOp(q(), null), null);
  });
  it("noteUrl names the note only", () => {
    const u = noteUrl("private/secret dir/My Note.md");
    assert.equal(u, "obsidian://open?file=My%20Note");
    assert.ok(!u.includes("secret") && !u.includes("private"));
  });
});

function mock(chunks: Record<string, object>, opStatus = 201, detail = "anchor_gone", opState = "pending") {
  const posts: { anchor?: string }[] = [];
  const f = (async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(init.body as string);
      posts.push(body.payload);
      const st = body.payload.anchor && opStatus === 422 ? 422 : opStatus === 422 ? 201 : opStatus;
      return new Response(JSON.stringify(st === 422 ? { detail: { code: detail } } : { status: opState }), { status: st });
    }
    const id = url.split("/").pop()!;
    return chunks[id] ? new Response(JSON.stringify(chunks[id])) : new Response("{}", { status: 404 });
  }) as typeof fetch;
  return { f, posts };
}
const ch = (id: string, status: string) => ({ id, document_id: "c", element_ids: [], bounds: {}, status, successor_of: null, created_by: "auto" });

describe("keepOnCanvas", () => {
  it("anchors on the first resolvable active chunk", async () => {
    const { f, posts } = mock({ dead: ch("dead", "orphaned"), live: ch("live", "active") });
    const r = await keepOnCanvas(q({ focus_chunk_ids: ["dead", "live"] }), "c", f);
    assert.ok(r.ok);
    assert.equal(posts[0].anchor, "live");
  });
  it("omits anchor when nothing resolves", async () => {
    const { f, posts } = mock({});
    await keepOnCanvas(q({ sources: [{ type: "chunk", id: "nope" }] }), "c", f);
    assert.ok(!("anchor" in posts[0]));
  });
  it("counts a replayed 200 as ok", async () => {
    const { f } = mock({}, 200);
    assert.ok((await keepOnCanvas(q(), "c", f)).ok);
  });
  it("does not retry other 422s", async () => {
    const { f, posts } = mock({ live: ch("live", "active") }, 422, "invalid");
    const r = await keepOnCanvas(q({ focus_chunk_ids: ["live"] }), "c", f);
    assert.ok(!r.ok);
    assert.equal(posts.length, 1);
  });
  it("reports an already resolved draft honestly", async () => {
    const { f } = mock({}, 200, "x", "rejected");
    const r = await keepOnCanvas(q(), "c", f);
    assert.ok(!r.ok && r.reason?.includes("rejected"));
  });
  it("retries once without anchor on 422", async () => {
    const { f, posts } = mock({ live: ch("live", "active") }, 422);
    const r = await keepOnCanvas(q({ focus_chunk_ids: ["live"] }), "c", f);
    assert.ok(r.ok);
    assert.equal(posts.length, 2);
    assert.ok(!("anchor" in posts[1]));
  });
});

describe("question push", () => {
  it("applyQuestionUpdate replaces by id, appends a new one, keeps order", () => {
    const a = q({ id: "a" }), b = q({ id: "b", status: "pending" });
    const got = applyQuestionUpdate([a, b], { ...b, status: "answered", answer_md: "x" });
    assert.deepEqual(got.map((x) => x.id), ["a", "b"]);
    assert.equal(got[1].status, "answered");
    assert.deepEqual(applyQuestionUpdate([a], b).map((x) => x.id), ["a", "b"]);
  });
  it("the bus delivers a push, null means refetch, and unsubscribe stops it", () => {
    const seen: unknown[] = [];
    const off = subscribeQuestions((x) => seen.push(x));
    const p = q({ id: "p" });
    publishQuestion(p);
    publishQuestion(null);
    off();
    publishQuestion(p);
    assert.deepEqual(seen, [p, null]);
  });
});

describe("runnerLine", () => {
  it("says nothing for answered rows and plain pending ones", () => {
    assert.equal(runnerLine(q({ status: "answered", runner_status: "failed", runner_error: "x" })), null);
    assert.equal(runnerLine(q({ status: "pending" })), null);
  });
  it("shows the failure reason, the retry reason and running", () => {
    assert.match(runnerLine(q({ status: "pending", runner_status: "failed", runner_error: "exit 2" }))!, /failed.*exit 2/);
    assert.match(runnerLine(q({ status: "pending", runner_error: "timeout after 180s" }))!, /timeout after 180s/);
    assert.match(runnerLine(q({ status: "pending", runner_status: "running" }))!, /Answering/);
  });
});
