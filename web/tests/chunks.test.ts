import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import {
  jumpNotice,
  jumpPlan,
  listChunks,
  liveIds,
  resolveChunk,
  toScreen,
  viewForBounds,
  type Chunk,
} from "../src/chunks.ts";

function chunk(id: string, over: Partial<Chunk> = {}): Chunk {
  return {
    id,
    document_id: "doc",
    element_ids: [`${id}-a`, `${id}-b`],
    bounds: { x: 0, y: 0, width: 100, height: 50 },
    status: "active",
    successor_of: null,
    created_by: "auto",
    ...over,
  };
}

// Fake API: GET /regions/{id} from a table, everything else recorded.
function api(rows: Record<string, Chunk>, opts: { fail?: boolean } = {}) {
  const calls: string[] = [];
  const fetchFn = (async (url: string) => {
    calls.push(url);
    if (opts.fail) throw new TypeError("network");
    const m = /^\/regions\/([^/?]+)$/.exec(url);
    if (m) {
      const row = rows[decodeURIComponent(m[1])];
      return new Response(row ? JSON.stringify(row) : '{"detail":"region not found"}', {
        status: row ? 200 : 404,
      });
    }
    if (url.startsWith("/documents/doc/regions?")) {
      return new Response(JSON.stringify(Object.values(rows)), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
  return { fetchFn, calls };
}

describe("resolveChunk", () => {
  it("returns an active chunk as found", async () => {
    const { fetchFn, calls } = api({ c1: chunk("c1") });
    const r = await resolveChunk("c1", "doc", fetchFn);
    assert.equal(r.outcome, "found");
    assert.equal(r.chunk?.id, "c1");
    assert.deepEqual(calls, ["/regions/c1"]);
  });

  it("follows successor_of through a chain of orphans to the active chunk", async () => {
    const { fetchFn } = api({
      old: chunk("old", { status: "orphaned", successor_of: "mid" }),
      mid: chunk("mid", { status: "orphaned", successor_of: "new" }),
      new: chunk("new"),
    });
    const r = await resolveChunk("old", "doc", fetchFn);
    assert.equal(r.outcome, "successor");
    assert.equal(r.chunk?.id, "new");
    assert.equal(r.requested, "old");
  });

  it("opens an orphan with no successor at its old bounds", async () => {
    const { fetchFn } = api({ gone: chunk("gone", { status: "orphaned" }) });
    const r = await resolveChunk("gone", "doc", fetchFn);
    assert.equal(r.outcome, "orphaned");
    assert.equal(r.chunk?.id, "gone");
  });

  it("stops at the last reachable orphan when a successor is missing", async () => {
    const { fetchFn } = api({ a: chunk("a", { status: "orphaned", successor_of: "nope" }) });
    const r = await resolveChunk("a", "doc", fetchFn);
    assert.equal(r.outcome, "orphaned");
    assert.equal(r.chunk?.id, "a");
  });

  it("terminates on a successor cycle", async () => {
    const { fetchFn, calls } = api({
      a: chunk("a", { status: "orphaned", successor_of: "b" }),
      b: chunk("b", { status: "orphaned", successor_of: "a" }),
    });
    const r = await resolveChunk("a", "doc", fetchFn);
    assert.equal(r.outcome, "orphaned");
    assert.deepEqual(calls, ["/regions/a", "/regions/b"]);
  });

  it("treats an unknown id, a manual region or another canvas's chunk as missing", async () => {
    const { fetchFn } = api({
      other: chunk("other", { document_id: "elsewhere" }),
      manual: { ...chunk("manual"), created_by: "user" },
    });
    assert.equal((await resolveChunk("zzz", "doc", fetchFn)).outcome, "missing");
    assert.equal((await resolveChunk("other", "doc", fetchFn)).outcome, "missing");
    assert.equal((await resolveChunk("manual", "doc", fetchFn)).outcome, "missing");
  });

  it("reports a network failure as error, not missing", async () => {
    const { fetchFn } = api({}, { fail: true });
    assert.equal((await resolveChunk("c1", "doc", fetchFn)).outcome, "error");
  });

  it("does not walk past an active chunk even if it still names a successor", async () => {
    const { fetchFn, calls } = api({ c1: chunk("c1", { successor_of: "c2" }), c2: chunk("c2") });
    const r = await resolveChunk("c1", "doc", fetchFn);
    assert.equal(r.outcome, "found");
    assert.deepEqual(calls, ["/regions/c1"]);
  });

  it("reports a failed successor lookup as error, not as a gone chunk", async () => {
    const rows = { a: chunk("a", { status: "orphaned", successor_of: "b" }) };
    const fetchFn = (async (url: string) =>
      url === "/regions/a" ? new Response(JSON.stringify(rows.a)) : new Response("oops", { status: 503 })) as unknown as typeof fetch;
    const r = await resolveChunk("a", "doc", fetchFn);
    assert.equal(r.outcome, "error");
    assert.equal(r.chunk, null);
  });

  it("encodes the id into the path", async () => {
    const { fetchFn, calls } = api({});
    await resolveChunk("a/b?c", "doc", fetchFn);
    assert.deepEqual(calls, ["/regions/a%2Fb%3Fc"]);
  });
});

describe("resolveChunk limits", () => {
  it("stops following at a successor on another canvas", async () => {
    const { fetchFn } = api({
      a: chunk("a", { status: "orphaned", successor_of: "x" }),
      x: chunk("x", { document_id: "elsewhere" }),
    });
    const r = await resolveChunk("a", "doc", fetchFn);
    assert.equal(r.outcome, "orphaned");
    assert.equal(r.chunk?.id, "a");
  });

  it("gives up after ten hops", async () => {
    const rows: Record<string, Chunk> = {};
    for (let i = 0; i < 20; i++) rows[`n${i}`] = chunk(`n${i}`, { status: "orphaned", successor_of: `n${i + 1}` });
    const { fetchFn, calls } = api(rows);
    const r = await resolveChunk("n0", "doc", fetchFn);
    assert.equal(r.outcome, "orphaned");
    assert.equal(calls.length, 11);
  });

  it("passes an abort signal so a stalled request times out", async () => {
    let signal: AbortSignal | undefined;
    const fetchFn = (async (_u: string, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Response(JSON.stringify(chunk("c1")), { status: 200 });
    }) as unknown as typeof fetch;
    await resolveChunk("c1", "doc", fetchFn);
    assert.ok(signal instanceof AbortSignal);
  });
});

describe("request timeout", () => {
  // A fetch that resolves headers at once and then never finishes the body unless aborted,
  // as a real fetch does when its signal fires.
  const stalledBody = (async (_u: string, init?: RequestInit) => ({
    ok: true,
    status: 200,
    json: () =>
      new Promise((_r, reject) => init?.signal?.addEventListener("abort", () => reject(new Error("aborted")))),
  })) as unknown as typeof fetch;

  // Settled value of `p` a few event-loop turns after the tick, or "pending" (fail fast, never hang).
  const settled = <T,>(p: Promise<T>) =>
    Promise.race([p, new Promise<"pending">((r) => setImmediate(() => setImmediate(() => r("pending"))))]);

  it("ends a lookup whose body stalls as error after the timeout", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const p = resolveChunk("c1", "doc", stalledBody);
      await new Promise((r) => setImmediate(r));
      mock.timers.tick(8000);
      const r = await settled(p);
      assert.notEqual(r, "pending", "the lookup is still hanging after the timeout");
      assert.equal(r !== "pending" && r.outcome, "error");
    } finally {
      mock.timers.reset();
    }
  });

  it("ends a stalled chunk list as an empty list", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const p = listChunks("doc", stalledBody);
      await new Promise((r) => setImmediate(r));
      mock.timers.tick(8000);
      assert.deepEqual(await settled(p), []);
    } finally {
      mock.timers.reset();
    }
  });
});

describe("jumpPlan", () => {
  const scene = [{ id: "c1-a" }, { id: "c1-b", isDeleted: true }];

  it("selects the live strokes of a found or successor chunk", () => {
    assert.deepEqual(jumpPlan({ outcome: "found", requested: "c1", chunk: chunk("c1") }, scene), {
      kind: "select",
      ids: ["c1-a"],
    });
    assert.deepEqual(jumpPlan({ outcome: "successor", requested: "old", chunk: chunk("c1") }, scene), {
      kind: "select",
      ids: ["c1-a"],
    });
  });

  it("opens an orphan at its old bounds even if some of its strokes are still live", () => {
    const c = chunk("c1", { status: "orphaned", bounds: { x: 1, y: 2, width: 3, height: 4 } });
    assert.deepEqual(jumpPlan({ outcome: "orphaned", requested: "c1", chunk: c }, scene), {
      kind: "bounds",
      bounds: { x: 1, y: 2, width: 3, height: 4 },
    });
  });

  it("falls back to the bounds when none of the strokes are live locally", () => {
    const plan = jumpPlan({ outcome: "found", requested: "c1", chunk: chunk("c1") }, [{ id: "other" }]);
    assert.equal(plan?.kind, "bounds");
  });

  it("does nothing without a chunk", () => {
    assert.equal(jumpPlan({ outcome: "missing", requested: "z", chunk: null }, scene), null);
  });
});

describe("jumpNotice", () => {
  it("is silent for a found chunk and explains every other outcome", () => {
    assert.equal(jumpNotice({ outcome: "found", requested: "c1", chunk: chunk("c1") }), null);
    assert.match(jumpNotice({ outcome: "successor", requested: "old", chunk: chunk("new") })!, /source changed.*old.*new/i);
    assert.match(jumpNotice({ outcome: "orphaned", requested: "g", chunk: chunk("g") })!, /source changed.*where it was/i);
    // A chain that ends at a later orphan names the chunk whose box is shown.
    assert.match(jumpNotice({ outcome: "orphaned", requested: "g", chunk: chunk("h") })!, /no longer exists.*where chunk h was/i);
    assert.match(jumpNotice({ outcome: "missing", requested: "z", chunk: null })!, /not found/i);
    assert.match(jumpNotice({ outcome: "error", requested: "z", chunk: null })!, /could not load/i);
  });
});

describe("listChunks", () => {
  it("lists only the active chunks of the canvas", async () => {
    const { fetchFn, calls } = api({ a: chunk("a"), b: chunk("b", { status: "orphaned" }) });
    const rows = await listChunks("doc", fetchFn);
    assert.deepEqual(rows.map((c) => c.id), ["a"]);
    assert.equal(calls[0], "/documents/doc/regions?chunks=true&limit=500");
  });

  it("returns an empty list when the API fails", async () => {
    const { fetchFn } = api({}, { fail: true });
    assert.deepEqual(await listChunks("doc", fetchFn), []);
  });
});

describe("liveIds", () => {
  it("keeps only ids present and not deleted in the scene", () => {
    const scene = [
      { id: "c1-a", isDeleted: false },
      { id: "c1-b", isDeleted: true },
      { id: "other", isDeleted: false },
    ];
    assert.deepEqual(liveIds(chunk("c1"), scene), ["c1-a"]);
  });
});

describe("viewport maths", () => {
  const viewport = { width: 1000, height: 800 };

  it("centres the bounds and fits them with a margin, never above 100%", () => {
    const v = viewForBounds({ x: 100, y: 200, width: 400, height: 100 }, viewport);
    assert.equal(v.zoom, 1);
    // Centre of the bounds lands at the centre of the viewport.
    const s = toScreen({ x: 100, y: 200, width: 400, height: 100 }, v);
    assert.equal(s.left + s.width / 2, 500);
    assert.equal(s.top + s.height / 2, 400);
  });

  it("zooms out for large bounds and clamps a degenerate box", () => {
    const v = viewForBounds({ x: 0, y: 0, width: 4000, height: 100 }, viewport);
    assert.ok(v.zoom < 0.25 && v.zoom > 0.2);
    // Never below Excalidraw's minimum zoom of 10%.
    assert.equal(viewForBounds({ x: 0, y: 0, width: 1e6, height: 10 }, viewport).zoom, 0.1);
    const z = viewForBounds({ x: 5, y: 5, width: 0, height: 0 }, viewport);
    assert.equal(z.zoom, 1);
    assert.ok(Number.isFinite(z.scrollX) && Number.isFinite(z.scrollY));
  });

  it("maps scene bounds to screen pixels through scroll and zoom", () => {
    const s = toScreen({ x: 10, y: 20, width: 30, height: 40 }, { scrollX: 5, scrollY: -10, zoom: 2 });
    assert.deepEqual(s, { left: 30, top: 20, width: 60, height: 80 });
  });
});
