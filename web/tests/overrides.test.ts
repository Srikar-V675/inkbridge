import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Chunk } from "../src/chunks.ts";
import { planOverride, sendOverride } from "../src/overrides.ts";

function chunk(id: string, element_ids: string[]): Chunk {
  return {
    id,
    document_id: "doc",
    element_ids,
    bounds: { x: 0, y: 0, width: 1, height: 1 },
    status: "active",
    successor_of: null,
    created_by: "auto",
  };
}

const chunks = [chunk("A", ["a1", "a2", "a3"]), chunk("B", ["b1", "b2"]), chunk("C", ["c1"])];

describe("planOverride", () => {
  it("asks for a selection when nothing chunked is selected", () => {
    assert.equal(planOverride([], chunks).kind, "none");
    assert.equal(planOverride(["draft-1"], chunks).kind, "none");
  });

  it("merges every chunk the selection touches, in chunk order, once each", () => {
    assert.deepEqual(planOverride(["b1", "a2", "a3", "x"], chunks), { kind: "merge", chunkIds: ["A", "B"] });
    assert.deepEqual(planOverride(["c1", "a1", "b2"], chunks), { kind: "merge", chunkIds: ["A", "B", "C"] });
  });

  it("splits a part of one chunk off, ignoring selected ids outside any chunk", () => {
    assert.deepEqual(planOverride(["a3", "a1", "draft"], chunks), {
      kind: "split",
      chunkId: "A",
      elementIds: ["a1", "a3"],
    });
  });

  it("does nothing when the selection already is a whole chunk", () => {
    const p = planOverride(["b1", "b2"], chunks);
    assert.equal(p.kind, "none");
    assert.match((p as { reason: string }).reason, /already/i);
  });
});

describe("sendOverride", () => {
  function fake(status: number, body: unknown) {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchFn = (async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    }) as unknown as typeof fetch;
    return { fetchFn, calls };
  }

  it("posts a merge and returns the new chunk id", async () => {
    const { fetchFn, calls } = fake(200, { chunk: { id: "N" }, orphaned: ["A", "B"] });
    const r = await sendOverride("my doc", { kind: "merge", chunkIds: ["A", "B"] }, fetchFn);
    assert.deepEqual(r, { ok: true, ids: ["N"] });
    assert.equal(calls[0].url, "/documents/my%20doc/chunks/merge");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { chunk_ids: ["A", "B"] });
  });

  it("posts a split and returns both new ids", async () => {
    const { fetchFn, calls } = fake(200, { chunks: [{ id: "S" }, { id: "R" }], orphaned: ["A"] });
    const r = await sendOverride("doc", { kind: "split", chunkId: "A", elementIds: ["a1"] }, fetchFn);
    assert.deepEqual(r, { ok: true, ids: ["S", "R"] });
    assert.equal(calls[0].url, "/documents/doc/chunks/split");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { chunk_id: "A", element_ids: ["a1"] });
  });

  it("reports the server's reason on a refusal and a network failure as such", async () => {
    const { fetchFn } = fake(409, { detail: "chunk A is orphaned (already replaced); reload the chunk list" });
    const r = await sendOverride("doc", { kind: "merge", chunkIds: ["A", "B"] }, fetchFn);
    assert.deepEqual(r, { ok: false, message: "chunk A is orphaned (already replaced); reload the chunk list" });
    const down = (async () => {
      throw new TypeError("network");
    }) as unknown as typeof fetch;
    const d = await sendOverride("doc", { kind: "merge", chunkIds: ["A", "B"] }, down);
    assert.equal(d.ok, false);
    assert.match((d as { message: string }).message, /could not reach/i);
  });

  it("never sends a request for a plan that does nothing", async () => {
    const { fetchFn, calls } = fake(200, {});
    const r = await sendOverride("doc", { kind: "none", reason: "x" }, fetchFn);
    assert.equal(r.ok, false);
    assert.equal(calls.length, 0);
  });
});
