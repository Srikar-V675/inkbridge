import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Chunk } from "../src/chunks.ts";
import {
  chunkMark,
  connectorIds,
  overrideUi,
  planOverride,
  sendOverride,
  toggleChunk,
} from "../src/overrides.ts";

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

describe("connectors", () => {
  const scene = [
    { id: "a1", type: "freedraw" },
    { id: "a2", type: "freedraw" },
    { id: "ar", type: "arrow" },
    { id: "arl", type: "text", containerId: "ar" },
    { id: "boxl", type: "text", containerId: "a1" },
  ];
  const withArrow = [chunk("A", ["a1", "a2", "ar", "arl"]), chunk("B", ["b1"])];

  it("finds arrows, lines and their labels only", () => {
    assert.deepEqual([...connectorIds(scene)].sort(), ["ar", "arl"]);
  });

  it("does not offer a split when the ink selected is the whole chunk", () => {
    const p = planOverride(["a1", "a2"], withArrow, connectorIds(scene));
    assert.equal(p.kind, "none");
  });

  it("splits only ink and never merges through a selected arrow alone", () => {
    assert.deepEqual(planOverride(["a1", "ar"], withArrow, connectorIds(scene)), {
      kind: "split",
      chunkId: "A",
      elementIds: ["a1"],
    });
    assert.equal(planOverride(["ar", "arl"], withArrow, connectorIds(scene)).kind, "none");
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

const fullScene = ["a1", "a2", "a3", "b1", "b2", "c1"].map((id) => ({ id }));

describe("toggleChunk", () => {
  it("selects all of a chunk's live ink, and a second tap adds another chunk", () => {
    const a = chunks[0];
    const b = chunks[1];
    const one = toggleChunk([], a, fullScene);
    assert.deepEqual([...one].sort(), ["a1", "a2", "a3"]);
    const two = toggleChunk(one, b, fullScene);
    assert.deepEqual([...two].sort(), ["a1", "a2", "a3", "b1", "b2"]);
    const back = toggleChunk(two, a, fullScene);
    assert.deepEqual([...back].sort(), ["b1", "b2"]);
  });

  it("ignores ids missing from the scene or deleted, and keeps unrelated selected ids", () => {
    const scene = [{ id: "a1" }, { id: "a2" }, { id: "a3", isDeleted: true }];
    assert.deepEqual([...toggleChunk(["draft-1"], chunks[0], scene)].sort(), ["a1", "a2", "draft-1"]);
    const noA3 = [{ id: "a1" }, { id: "a2" }];
    assert.deepEqual([...toggleChunk([], chunks[0], noA3)].sort(), ["a1", "a2"]);
  });

  it("leaves the selection alone for a chunk with no live ink", () => {
    const gone = chunk("G", ["g1"]);
    assert.deepEqual(toggleChunk(["a1"], gone, fullScene), ["a1"]);
  });

  it("feeds planOverride: two tapped chunks merge, one tapped chunk is a whole chunk", () => {
    const both = toggleChunk(toggleChunk([], chunks[0], fullScene), chunks[1], fullScene);
    assert.deepEqual(planOverride(both, chunks), { kind: "merge", chunkIds: ["A", "B"] });
    const only = toggleChunk([], chunks[0], fullScene);
    const plan = planOverride(only, chunks);
    assert.equal(plan.kind, "none");
    const ui = overrideUi(plan);
    assert.equal(ui.canMerge, false);
    assert.equal(ui.canSplit, false);
  });
});

describe("chunkMark", () => {
  it("is none, partial or full by the ink selected", () => {
    assert.equal(chunkMark([], chunks[0]), "none");
    assert.equal(chunkMark(["a1"], chunks[0]), "partial");
    assert.equal(chunkMark(["a1", "a2", "a3"], chunks[0]), "full");
  });

  it("ignores connectors when deciding full", () => {
    assert.equal(chunkMark(["a1", "a2"], chunks[0], new Set(["a3"])), "full");
    assert.equal(chunkMark(["a1"], chunks[0], new Set(["a3"])), "partial");
  });

  it("a chunk with no ink (connectors only) is none", () => {
    const arrows = chunk("R", ["ar"]);
    assert.equal(chunkMark(["ar"], arrows, new Set(["ar"])), "none");
  });
});

describe("overrideUi", () => {
  it("offers Merge for a merge plan, with the chunk count", () => {
    const ui = overrideUi({ kind: "merge", chunkIds: ["A", "B", "C"] });
    assert.equal(ui.canMerge, true);
    assert.equal(ui.canSplit, false);
    assert.match(ui.hint, /3/);
  });

  it("offers Split for a split plan", () => {
    const ui = overrideUi({ kind: "split", chunkId: "A", elementIds: ["a1"] });
    assert.equal(ui.canMerge, false);
    assert.equal(ui.canSplit, true);
    assert.ok(ui.hint.length > 0);
  });

  it("offers neither for none, with a hint; whole-chunk reason is kept", () => {
    const empty = overrideUi({ kind: "none", reason: "Select ink that belongs to a chunk." });
    assert.equal(empty.canMerge, false);
    assert.equal(empty.canSplit, false);
    assert.match(empty.hint, /Tap chunk tabs/);
    const whole = overrideUi({ kind: "none", reason: "The selection already is a whole chunk." });
    assert.equal(whole.canSplit, false);
    assert.match(whole.hint, /already is a whole chunk/);
  });
});
