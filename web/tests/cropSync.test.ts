import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { CropSync, type StaleChunk } from "../src/cropSync.ts";

const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
};
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const chunk = (id: string, ids = [`${id}-e`], status = "active"): StaleChunk => ({
  id,
  element_ids: ids,
  status,
  png_stale: true,
});

type Call = { url: string; method: string; version?: string | null };

function harness(
  opts: { lists?: StaleChunk[][]; putStatus?: number[]; settled?: () => number | null; start?: boolean } = {},
) {
  const lists = opts.lists ?? [[chunk("c1"), chunk("c2")]];
  const putStatus = opts.putStatus ?? [];
  const calls: Call[] = [];
  const exported: string[][] = [];
  const fetchFn = (async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const version = init?.body instanceof FormData ? (init.body.get("scene_version") as string) : undefined;
    calls.push({ url, method, version });
    if (method === "GET") return json(200, lists.length > 1 ? lists.shift() : lists[0]);
    return json(putStatus.shift() ?? 200, {});
  }) as unknown as typeof fetch;
  const h = {
    calls,
    exported,
    puts: () => calls.filter((c) => c.method === "PUT"),
    gets: () => calls.filter((c) => c.method === "GET"),
    advance: async (ms: number) => {
      mock.timers.tick(ms);
      await settle();
    },
    onExport: (_ids: readonly string[]) => {},
    sync: null as unknown as CropSync,
  };
  h.sync = new CropSync({
    documentId: "doc 1",
    fetchFn,
    settledVersion: opts.settled ?? (() => 4),
    yieldFn: async () => {},
    exportPng: async (ids) => {
      exported.push([...ids]);
      h.onExport(ids);
      return new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
    },
  });
  if (opts.start !== false) h.sync.start(1e9); // the canvas is showing the loaded scene
  return h;
}

describe("CropSync", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout", "Date"] }));
  afterEach(() => mock.timers.reset());

  it("waits for about 2 s of idle, then uploads every stale chunk with the scene version", async () => {
    const h = harness();
    h.sync.activity();
    h.sync.request();
    await h.advance(1900);
    assert.equal(h.calls.length, 0, "nothing before the canvas has been idle for 2 s");
    await h.advance(100);
    assert.equal(h.gets()[0].url, "/documents/doc%201/regions?chunks=true&png_stale=true&status=active&limit=500");
    assert.deepEqual(h.exported, [["c1-e"], ["c2-e"]]);
    assert.deepEqual(
      h.puts().map((c) => [c.url, c.version]),
      [
        ["/regions/c1/image", "4"],
        ["/regions/c2/image", "4"],
      ],
    );
  });

  it("never exports while a pointer is down, however long the stroke lasts", async () => {
    const h = harness();
    h.sync.setDrawing(true);
    h.sync.request();
    await h.advance(10_000);
    assert.equal(h.exported.length, 0);
    assert.equal(h.calls.length, 0, "not even the stale list is fetched while the pen is down");
    h.sync.setDrawing(false);
    await h.advance(1999);
    assert.equal(h.exported.length, 0, "the idle clock restarts when the pen lifts");
    await h.advance(1);
    assert.equal(h.exported.length, 2);
  });

  it("stops the pass when drawing starts mid-pass and catches up after the next idle", async () => {
    const h = harness({ lists: [[chunk("c1"), chunk("c2"), chunk("c3")], [chunk("c2"), chunk("c3")]] });
    h.onExport = (ids) => {
      if (ids[0] === "c1-e") h.sync.setDrawing(true); // pen goes down while c1 is exported
    };
    h.sync.request();
    await h.advance(2000);
    assert.deepEqual(h.exported, [["c1-e"]]);
    assert.equal(h.puts().length, 0, "a crop exported while drawing began is discarded");
    await h.advance(5000);
    assert.equal(h.exported.length, 1, "still drawing: nothing more");
    h.onExport = () => {};
    h.sync.setDrawing(false);
    await h.advance(2000);
    assert.deepEqual(h.puts().map((c) => c.url), ["/regions/c2/image", "/regions/c3/image"]);
  });

  it("does nothing while local edits are unsaved; the next request after the save runs", async () => {
    let version: number | null = null;
    const h = harness({ settled: () => version });
    h.sync.request();
    await h.advance(3000);
    assert.equal(h.calls.length, 0);
    version = 7;
    h.sync.request(); // App calls this on every "saved" state
    await h.advance(2000);
    assert.deepEqual(h.puts().map((c) => c.version), ["7", "7"]);
  });

  it("a request made while a save is in flight runs once the save settles, without another request", async () => {
    let version: number | null = null;
    const h = harness({ settled: () => version });
    h.sync.request(); // e.g. load() emits "saved" during a conflict reload, before the save ends
    await h.advance(2000);
    assert.equal(h.calls.length, 0);
    version = 5; // the save finished, but no further "saved" state follows
    await h.advance(2000);
    assert.deepEqual(h.puts().map((c) => c.version), ["5", "5"]);
  });

  it("a scene change during an export (no pointer involved) drops that crop", async () => {
    const h = harness();
    h.onExport = (ids) => {
      if (ids[0] === "c1-e") {
        mock.timers.tick(1); // a keyboard edit or undo lands while c1 is exported
        h.sync.activity();
      }
    };
    h.sync.request();
    await h.advance(2000);
    assert.equal(h.puts().length, 0, "the crop exported during the change is not uploaded");
  });

  it("aborts when the scene version changes during the pass", async () => {
    let version = 3;
    const h = harness({ start: false });
    h.sync = new CropSync({
      documentId: "d",
      fetchFn: (async (url: string, init?: RequestInit) => {
        h.calls.push({ url, method: init?.method ?? "GET" });
        if (!init?.method) return json(200, [chunk("c1"), chunk("c2")]);
        version = 4; // a save completed while the first upload was in flight
        return json(200, {});
      }) as unknown as typeof fetch,
      settledVersion: () => version,
      yieldFn: async () => {},
      exportPng: async (ids) => (h.exported.push([...ids]), new Blob([])),
    });
    h.sync.start(1e9);
    await h.advance(2000);
    assert.deepEqual(h.exported, [["c1-e"]]);
  });

  it("skips orphaned chunks and chunks with nothing left to draw", async () => {
    const h = harness({ lists: [[chunk("gone", ["x"], "orphaned"), chunk("c1")]] });
    h.sync.request();
    await h.advance(2000);
    assert.deepEqual(h.exported, [["c1-e"]]);
  });

  it("a 409 (tab behind the stored scene) stops passes until the tab's version changes", async () => {
    let version = 4;
    const h = harness({ putStatus: [409], settled: () => version });
    await h.advance(2000);
    assert.equal(h.puts().length, 1);
    for (let i = 0; i < 5; i++) {
      h.sync.request(); // what every poll does
      await h.advance(2000);
    }
    assert.equal(h.gets().length, 1, "no list, export or upload again at the refused version");
    version = 5; // this tab saved (or reloaded)
    h.sync.request();
    await h.advance(2000);
    assert.deepEqual(h.puts().map((c) => c.version), ["4", "5", "5"]);
  });

  it("start() catches up on open and polls until the WebSocket exists", async () => {
    const h = harness({ lists: [[]], start: false });
    h.sync.request(); // a "saved" state before the canvas has mounted is held, not run
    await h.advance(5000);
    assert.equal(h.gets().length, 0, "nothing runs before start()");
    h.sync.start(30_000);
    await h.advance(2000);
    assert.equal(h.gets().length, 1, "a reopened tab lists stale crops right away");
    await h.advance(30_000);
    assert.equal(h.gets().length, 2);
    h.sync.dispose();
    await h.advance(60_000);
    assert.equal(h.gets().length, 2, "disposed: no more polling");
  });

  it("a failed list is retried by the next poll, not immediately", async () => {
    const h = harness({ start: false });
    let first = true;
    const sync = new CropSync({
      documentId: "d",
      fetchFn: (async (url: string, init?: RequestInit) => {
        h.calls.push({ url, method: init?.method ?? "GET" });
        if (first) {
          first = false;
          throw new TypeError("offline");
        }
        return init?.method ? json(200, {}) : json(200, [chunk("c1")]);
      }) as unknown as typeof fetch,
      settledVersion: () => 1,
      yieldFn: async () => {},
      exportPng: async () => new Blob([]),
    });
    sync.start(30_000);
    await h.advance(2000);
    assert.equal(h.gets().length, 1);
    await h.advance(27_990);
    assert.equal(h.gets().length, 1);
    await h.advance(10);
    assert.equal(h.puts().length, 1);
    sync.dispose();
  });
});
