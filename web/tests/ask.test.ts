import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { fileName, focusIds, keepOnCanvas, keepOp, plainText, type Question } from "../src/ask.ts";

const q = (over: Partial<Question> = {}): Question => ({
  id: "abc123", document_id: "c", parent_id: null, text: "t", focus_element_ids: [], focus_chunk_ids: [],
  status: "answered", answer_md: "Hello **world**", sources: [], created_at: "", ...over,
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
  it("caps length", () => assert.equal(plainText("a".repeat(20000)).length, 2000));
});

describe("keepOp", () => {
  it("shape and idempotent id", () => {
    const op = keepOp(q(), null);
    assert.equal(op.op_id, "keep-abc123");
    assert.deepEqual(Object.keys(op.payload), ["text"]);
    assert.deepEqual(Object.keys(keepOp(q(), "k1").payload).sort(), ["anchor", "text"]);
  });
});

function mock(chunks: Record<string, object>, opStatus = 201) {
  const posts: { anchor?: string }[] = [];
  const f = (async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(init.body as string);
      posts.push(body.payload);
      const st = body.payload.anchor && opStatus === 422 ? 422 : opStatus === 422 ? 201 : opStatus;
      return new Response("{}", { status: st });
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
  it("retries once without anchor on 422", async () => {
    const { f, posts } = mock({ live: ch("live", "active") }, 422);
    const r = await keepOnCanvas(q({ focus_chunk_ids: ["live"] }), "c", f);
    assert.ok(r.ok);
    assert.equal(posts.length, 2);
    assert.ok(!("anchor" in posts[1]));
  });
});
