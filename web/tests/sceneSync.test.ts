import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { SceneSync, deltaFor, mergeScenes, type SaveState, type SceneElement } from "../src/sync/sceneSync.ts";
import { setTimingSink, type TimingRecord } from "../src/lib/timing.ts";

const el = (id: string, version = 1, extra: Record<string, unknown> = {}): SceneElement => ({
  id,
  version,
  ...extra,
});
const settle = () => new Promise((r) => setImmediate(r));
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

type Call = { url: string; method: string; key?: string; raw?: string; signal?: AbortSignal | null; body?: { base_version: number; elements: SceneElement[] } };

function harness(responses: Array<Response | Error | (() => Response)>) {
  const calls: Call[] = [];
  const states: SaveState[] = [];
  const details: Array<string | undefined> = [];
  const reloads: SceneElement[][] = [];
  const stored: Record<string, string> = {};
  const fetchFn = (async (url: string, init?: RequestInit) => {
    calls.push({
      url,
      method: init?.method ?? "GET",
      key: (init?.headers as Record<string, string> | undefined)?.["x-inkbridge-save"],
      raw: init?.body as string | undefined,
      signal: init?.signal,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request " + url);
    if (next instanceof Error) throw next;
    return typeof next === "function" ? next() : next;
  }) as unknown as typeof fetch;
  const sync = new SceneSync({
    documentId: "default",
    fetchFn,
    storage: { setItem: (k, v) => void (stored[k] = v) },
    onState: (s, d) => (states.push(s), details.push(d)),
    onReload: (e) => reloads.push(e),
  });
  return { sync, calls, states, details, reloads, stored };
}

// A response the test releases by hand, to act while a request is in flight.
function deferred() {
  let release!: (r: Response) => void;
  const promise = new Promise<Response>((r) => (release = r));
  return { next: (() => promise) as unknown as () => Response, release };
}

describe("SceneSync", () => {
  it("reports the save time in the saved badge detail", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.flushNow();
    assert.equal(h.states.at(-1), "saved");
    assert.match(h.details.at(-1) ?? "", /^\d+ ms$/);
  });

  it("joins the server timing parts onto the scene.save record (INK-102)", async () => {
    const got: TimingRecord[] = [];
    setTimingSink((r) => void got.push(r));
    const timing = { recv: 1, queue: 2, lock: 3, work: 4, commit: 5, total: 15 };
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1, timing })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.flushNow();
    setTimingSink(() => {});
    const save = got.find((r) => r.name === "scene.save");
    assert.equal(save?.counts.s_lock, 3);
    assert.equal(save?.counts.s_total, 15);
    assert.ok(save && "elements" in save.counts && "sent" in save.counts && "bytes" in save.counts);
    assert.deepEqual(Object.keys(save ?? {}).sort(), ["counts", "ms", "name"]);
  });

  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());

  it("loads the scene and remembers its version", async () => {
    const h = harness([json(200, { version: 7, elements: [el("a")] })]);
    assert.deepEqual(await h.sync.load(), [el("a")]);
    assert.equal(h.calls[0].url, "/documents/default/scene");
    assert.equal(h.states.at(-1), "saved");
  });

  it("hasSaved is true only once the server confirmed the elements", async () => {
    const h = harness([
      json(200, { version: 1, elements: [el("a")] }),
      new Error("offline"),
      json(200, { version: 2 }),
    ]);
    await h.sync.load();
    assert.equal(h.sync.hasSaved(["a"]), true);
    h.sync.notify([el("a"), el("op:1")]);
    await h.sync.flushNow(); // the save fails: flushNow resolves anyway
    assert.equal(h.sync.hasSaved(["op:1"]), false);
    await h.sync.flushNow();
    assert.equal(h.sync.hasSaved(["a", "op:1"]), true);
  });

  it("reports an unknown canvas as an error", async () => {
    const h = harness([json(404, { detail: "no" })]);
    assert.equal(await h.sync.load(), null);
    assert.equal(h.states.at(-1), "error");
  });

  it("tells an unknown canvas (404) from a failed load", async () => {
    const h404 = harness([json(404, { detail: "no" })]);
    assert.equal(h404.sync.notFound, false);
    await h404.sync.load();
    assert.equal(h404.sync.notFound, true);
    const h500 = harness([json(500, { detail: "boom" })]);
    await h500.sync.load();
    assert.equal(h500.sync.notFound, false);
    const hDown = harness([new Error("down")]);
    await hDown.sync.load();
    assert.equal(hDown.sync.notFound, false);
  });

  it("never saves or backs up before the scene is loaded", async () => {
    const h = harness([]);
    assert.equal(h.sync.notify([el("a", 1)]), false);
    mock.timers.tick(5000);
    await settle();
    await h.sync.flushNow();
    await h.sync.close();
    assert.equal(h.calls.length, 0);
    assert.deepEqual(h.stored, {});
  });

  it("ignores onChange calls that did not change any element", async () => {
    const h = harness([json(200, { version: 1, elements: [el("a", 3)] })]);
    await h.sync.load();
    h.sync.notify([el("a", 3)]);
    mock.timers.tick(5000);
    await settle();
    assert.equal(h.calls.length, 1);
  });

  it("saves once after the debounce, sending base_version, and adopts the new version", async () => {
    const h = harness([
      json(200, { version: 4, elements: [] }),
      json(200, { version: 5 }),
      json(200, { version: 6 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    h.sync.notify([el("a", 2)]);
    assert.equal(h.states.at(-1), "dirty");
    mock.timers.tick(1499);
    await settle();
    assert.equal(h.calls.length, 1);
    mock.timers.tick(1);
    await settle();
    assert.equal(h.calls.length, 2);
    assert.deepEqual(h.calls[1].body, { base_version: 4, elements: [el("a", 2)] });
    assert.equal(h.states.at(-1), "saved");
    h.sync.notify([el("a", 3)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.calls[2].body?.base_version, 5);
  });

  it("does not restart the debounce or re-emit state for an unchanged pending edit", async () => {
    const h = harness([json(200, { version: 1, elements: [] }), json(200, { version: 2 })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    const emitted = h.states.length;
    mock.timers.tick(1000);
    h.sync.notify([el("a", 1)]); // Excalidraw re-fires onChange after every re-render
    h.sync.notify([el("a", 1)]);
    assert.equal(h.states.length, emitted);
    mock.timers.tick(500); // 1500 ms after the FIRST notify: the save must not have moved
    await settle();
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 1);
  });

  it("keeps pressures and simulatePressure=false in the saved body", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    const stroke = el("s", 1, { type: "freedraw", pressures: [0.3, 0.9], simulatePressure: false });
    h.sync.notify([stroke]);
    mock.timers.tick(1500);
    await settle();
    assert.deepEqual(h.calls[1].body?.elements[0], stroke);
  });

  it("saves edits made during a save afterwards, with the new base_version", async () => {
    let release!: (r: Response) => void;
    const h = harness([
      json(200, { version: 1, elements: [] }),
      () => {
        throw new Error("replaced below");
      },
    ]);
    // second response is a deferred promise: wrap fetch
    const pending = new Promise<Response>((r) => (release = r));
    const original = (h.sync as unknown as { fetchFn: typeof fetch }).fetchFn;
    let n = 0;
    (h.sync as unknown as { fetchFn: typeof fetch }).fetchFn = ((u: string, i?: RequestInit) =>
      ++n === 2 ? (h.calls.push({ url: u, method: "PUT", body: JSON.parse(i!.body as string) }), pending) : original(u, i)) as typeof fetch;
    await h.sync.load();
    n = 1;
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.states.at(-1), "saving");
    h.sync.notify([el("a", 2)]); // edit while the first PUT is in flight
    mock.timers.tick(1500); // its debounce fires while the PUT is still in flight, so it is skipped
    await settle();
    release(json(200, { version: 2 }));
    await settle();
    mock.timers.tick(1500);
    await settle();
    const puts = h.calls.filter((c) => c.method === "PUT");
    assert.equal(puts.length, 2);
    assert.equal(puts[1].body?.base_version, 2);
    assert.deepEqual(puts[1].body?.elements, [el("a", 2)]);
  });

  it("on 409 merges the server scene with ALL local edits, including ones made mid-save", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(409, { detail: { current_version: 9 } }),
      json(200, { version: 9, elements: [el("server", 4)] }),
      json(200, { version: 10 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("s1", 1)]);
    mock.timers.tick(1500);
    h.sync.notify([el("s1", 1), el("s2", 1)]); // drawn while the PUT is in flight
    await settle();
    assert.deepEqual(h.reloads.at(-1)?.map((e) => e.id).sort(), ["s1", "s2", "server"]);
    assert.equal(h.states.includes("conflict"), true);
    const backup = Object.entries(h.stored).find(([k]) => k.includes("conflict"));
    assert.deepEqual(JSON.parse(backup![1]).map((e: SceneElement) => e.id), ["s1", "s2"]);
    mock.timers.tick(1500); // the merged scene is saved against the reloaded version
    await settle();
    const put = h.calls.filter((c) => c.method === "PUT").at(-1)!;
    assert.equal(put.body?.base_version, 9);
    // the server element is already stored at the reloaded version: only our strokes travel
    assert.deepEqual(put.body?.elements.map((e) => e.id).sort(), ["s1", "s2"]);
  });

  it("a 409 reload asks for deleted elements too, the first load does not", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(409, { detail: {} }),
      json(200, { version: 2, elements: [] }),
      json(200, { version: 3 }),
    ]);
    await h.sync.load();
    assert.equal(h.calls[0].url, "/documents/default/scene");
    h.sync.notify([el("s1", 1)]);
    mock.timers.tick(1500);
    await settle();
    const gets = h.calls.filter((c) => c.method === "GET");
    assert.equal(gets[1].url, "/documents/default/scene?deleted=true");
  });

  it("a stroke another device deleted stays deleted after the conflict reload", async () => {
    const h = harness([
      json(200, { version: 1, elements: [el("x", 2)] }),
      json(409, { detail: {} }),
      json(200, { version: 5, elements: [el("x", 5, { isDeleted: true })] }),
      json(200, { version: 6 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("x", 2), el("y", 1)]);
    mock.timers.tick(1500);
    await settle();
    const merged = h.reloads.at(-1)!;
    assert.equal(merged.find((e) => e.id === "x")?.isDeleted, true);
  });

  it("mergeScenes keeps the newer version of an element and never drops a local one", () => {
    const merged = mergeScenes(
      [el("a", 2, { from: "server" }), el("b", 1)],
      [el("a", 3, { from: "local" }), el("c", 1)],
    );
    assert.deepEqual(merged.map((e) => [e.id, e.from ?? null]), [["a", "local"], ["b", null], ["c", null]]);
    assert.equal(mergeScenes([el("a", 5, { from: "server" })], [el("a", 5, { from: "local" })])[0].from, "server");
  });

  it("mergeScenes breaks version ties by versionNonce the same way on both tabs", () => {
    const a = el("x", 5, { versionNonce: 10, from: "A" });
    const b = el("x", 5, { versionNonce: 20, from: "B" });
    assert.equal(mergeScenes([b], [a])[0].from, "A"); // tab A: server holds B, lower nonce wins
    assert.equal(mergeScenes([a], [b])[0].from, "A"); // tab B: server holds A, A still wins
    assert.equal(mergeScenes([{ ...a, from: "S" }], [a])[0].from, "S"); // same nonce: server copy
  });

  it("keeps edits in memory after a 4xx and says they are unsaved", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(422, { detail: [] }),
      json(200, { version: 2 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.states.at(-1), "error");
    assert.match(h.details.at(-1) ?? "", /not saved/i);
    h.sync.notify([el("a", 1), el("b", 1)]); // next real edit tries again with everything
    mock.timers.tick(1500);
    await settle();
    assert.deepEqual(h.calls.at(-1)?.body?.elements.map((e) => e.id), ["a", "b"]);
  });

  it("flushNow waits for an in-flight save and then sends newer edits", async () => {
    let release!: (r: Response) => void;
    const h = harness([json(200, { version: 1, elements: [] })]);
    const gate = new Promise<Response>((r) => (release = r));
    let n = 0;
    const base = (h.sync as unknown as { fetchFn: typeof fetch }).fetchFn;
    (h.sync as unknown as { fetchFn: typeof fetch }).fetchFn = ((u: string, i?: RequestInit) => {
      if (i?.method === "PUT") {
        h.calls.push({ url: u, method: "PUT", body: JSON.parse(i.body as string) });
        return ++n === 1 ? gate : Promise.resolve(json(200, { version: 3 }));
      }
      return base(u, i);
    }) as typeof fetch;
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    h.sync.notify([el("a", 1), el("b", 1)]);
    const flushed = h.sync.flushNow();
    release(json(200, { version: 2 }));
    await flushed;
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 2);
    assert.equal(h.calls.at(-1)?.body?.base_version, 2);
  });

  it("retries a network failure with backoff and then saves", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      new TypeError("fetch failed"),
      json(200, { version: 2 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.states.at(-1), "retry");
    mock.timers.tick(2000);
    await settle();
    assert.equal(h.states.at(-1), "saved");
    assert.equal(h.calls.length, 3);
  });

  it("does not retry a 422 (it would loop forever)", async () => {
    const h = harness([json(200, { version: 1, elements: [] }), json(422, { detail: [] })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    mock.timers.tick(60000);
    await settle();
    assert.equal(h.states.at(-1), "error");
    assert.equal(h.calls.length, 2);
  });

  it("keeps strokes drawn while the conflict reload is in flight", async () => {
    const reload = deferred();
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(409, { detail: {} }),
      reload.next,
      json(200, { version: 10 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("s1", 1)]);
    mock.timers.tick(1500);
    await settle(); // the PUT got a 409 and the reload GET is now in flight
    h.sync.notify([el("s1", 1), el("s2", 1)]);
    reload.release(json(200, { version: 9, elements: [el("server", 4)] }));
    await settle();
    assert.deepEqual(h.reloads.at(-1)?.map((e) => e.id).sort(), ["s1", "s2", "server"]);
    mock.timers.tick(1500);
    await settle();
    const put = h.calls.filter((c) => c.method === "PUT").at(-1)!;
    // the server element is already stored at the reloaded version: only our strokes travel
    assert.deepEqual(put.body?.elements.map((e) => e.id).sort(), ["s1", "s2"]);
  });

  it("an element mutated in place during a save is saved again", async () => {
    const put = deferred();
    const h = harness([json(200, { version: 1, elements: [] }), put.next, json(200, { version: 3 })]);
    await h.sync.load();
    const a = el("a", 1);
    const scene = [a];
    h.sync.notify(scene);
    mock.timers.tick(1500);
    await settle();
    a.version = 2; // Excalidraw's mutateElement changes the same object
    h.sync.notify(scene);
    put.release(json(200, { version: 2 }));
    await settle();
    assert.notEqual(h.states.at(-1), "saved");
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 2);
    assert.equal(h.states.at(-1), "saved");
  });

  it("returning to the saved scene while a save is in flight is saved too", async () => {
    const put = deferred();
    const h = harness([json(200, { version: 1, elements: [] }), put.next, json(200, { version: 3 })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    h.sync.notify([]); // back to what the server last confirmed, before [a] lands
    put.release(json(200, { version: 2 }));
    await settle();
    mock.timers.tick(1500);
    await settle();
    const puts = h.calls.filter((c) => c.method === "PUT");
    assert.equal(puts.length, 2);
    assert.deepEqual(puts[1].body?.elements, []);
  });

  it("retries when the conflict reload fails instead of waiting for the next edit", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(409, { detail: {} }),
      new TypeError("fetch failed"),
      json(409, { detail: {} }),
      json(200, { version: 9, elements: [] }),
      json(200, { version: 10 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.states.at(-1), "retry");
    mock.timers.tick(2000);
    await settle();
    mock.timers.tick(1500);
    await settle();
    const put = h.calls.filter((c) => c.method === "PUT").at(-1)!;
    assert.equal(put.body?.base_version, 9);
    assert.deepEqual(put.body?.elements, [el("a", 1)]);
  });

  it("flushNow asks for keepalive for a small body; debounced saves do not", async () => {
    const inits: RequestInit[] = [];
    const sync = new SceneSync({
      documentId: "d",
      fetchFn: (async (_u: string, i?: RequestInit) => {
        inits.push(i ?? {});
        return i?.method === "PUT" ? json(200, { version: 2 }) : json(200, { version: 1, elements: [] });
      }) as unknown as typeof fetch,
      onState: () => {},
      onReload: () => {},
    });
    await sync.load();
    sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.equal(inits[1].keepalive, false);
    sync.notify([el("a", 2)]);
    await sync.flushNow();
    assert.equal(inits[2].keepalive, true);
  });

  it("a disposed instance no longer reports state", async () => {
    const h = harness([json(200, { version: 1, elements: [] })]);
    const p = h.sync.load();
    const before = h.states.length;
    h.sync.dispose();
    await p;
    assert.equal(h.states.length, before);
  });
  it("close() flushes a pending edit, then disposes", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.close();
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 1);
    assert.equal(h.sync.settledVersion(), null, "disposed");
  });

  it("close() backs the unsaved edits up when the final flush fails", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), new Error("offline")]);
    await h.sync.load();
    h.sync.notify([el("a"), el("b")]);
    await h.sync.close();
    const kept = JSON.parse(h.stored["inkbridge-conflict-backup-default"] ?? "null");
    assert.deepEqual(kept.map((e: SceneElement) => e.id), ["a", "b"]);
    assert.equal(h.sync.settledVersion(), null, "disposed");
  });

  it("close() backs the edits up on a server error and a rejection too", async () => {
    for (const status of [503, 422]) {
      const h = harness([json(200, { version: 0, elements: [] }), json(status, {})]);
      await h.sync.load();
      h.sync.notify([el("a")]);
      await h.sync.close();
      assert.ok(h.stored["inkbridge-conflict-backup-default"], `status ${status}`);
    }
  });

  it("close() after a 409 keeps the local ink backup", async () => {
    const h = harness([
      json(200, { version: 0, elements: [] }),
      json(409, { detail: { current_version: 5 } }),
      json(200, { version: 5, elements: [el("theirs")] }),
    ]);
    await h.sync.load();
    h.sync.notify([el("mine")]);
    await h.sync.close();
    const kept = JSON.parse(h.stored["inkbridge-conflict-backup-default"] ?? "null");
    assert.deepEqual(kept.map((e: SceneElement) => e.id), ["mine"], "the backup is the local scene, not the merge");
  });

  it("close() writes no backup when the flush lands", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.close();
    assert.equal(h.stored["inkbridge-conflict-backup-default"], undefined);
  });

  it("close() with nothing pending sends nothing", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    await h.sync.close();
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 0);
    assert.equal(h.sync.settledVersion(), null);
  });

  it("settledVersion is the saved version only when nothing is pending or in flight", async () => {
    const save = deferred();
    const h = harness([json(200, { version: 3, elements: [el("a")] }), save.next]);
    assert.equal(h.sync.settledVersion(), null, "not loaded yet");
    await h.sync.load();
    assert.equal(h.sync.settledVersion(), 3);
    assert.equal(h.sync.notify([el("a")]), false, "unchanged scene");
    assert.equal(h.sync.notify([el("a", 2)]), true);
    assert.equal(h.sync.settledVersion(), null, "edit not saved yet");
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.sync.settledVersion(), null, "save in flight");
    save.release(json(200, { version: 4 }));
    await settle();
    await settle();
    assert.equal(h.sync.settledVersion(), 4);
  });
});

describe("delta saves (INK-075)", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());

  it("sends only the changed and new elements after a load", async () => {
    const h = harness([
      json(200, { version: 3, elements: [el("a"), el("b")] }),
      json(200, { version: 4 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a"), el("b", 2), el("c")]);
    await h.sync.flushNow();
    assert.deepEqual(h.calls[1].body, {
      base_version: 3,
      elements: [el("b", 2), el("c")],
      delta: true,
    });
  });

  it("diffs against the last confirmed save, and resends a failed save unchanged (INK-083)", async () => {
    const h = harness([
      json(200, { version: 1, elements: [el("a"), el("b")] }),
      new Error("offline"),
      json(200, { version: 2 }),
      json(200, { version: 3 }),
      json(200, { version: 4 }),
      json(200, { version: 5 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 2), el("b")]);
    await h.sync.flushNow(); // fails
    h.sync.notify([el("a", 2), el("b", 2)]);
    await h.sync.flushNow(); // the failed request is resent as it was
    assert.deepEqual(h.calls[2].body?.elements, [el("a", 2)]);
    await h.sync.flushNow(); // the newer edit follows, diffed against the confirmed save
    assert.deepEqual(h.calls[3].body?.elements, [el("b", 2)]);
    h.sync.notify([el("a", 2), el("b", 3)]);
    await h.sync.flushNow();
    assert.deepEqual(h.calls[4].body?.elements, [el("b", 3)]);
  });

  it("does a full save when an element the server holds is no longer in the list", () => {
    const base = new Map([["a", 1], ["b", 1]]);
    assert.equal(deltaFor(base, [el("a", 2)]), null);
    assert.equal(deltaFor(null, [el("a")]), null);
    assert.equal(deltaFor(base, [el("a", 2), el("b", 2)]), null); // nothing smaller to send
  });

  it("after a conflict reload the next save is diffed against the reloaded scene", async () => {
    const h = harness([
      json(200, { version: 1, elements: [el("a")] }),
      json(409, { detail: { current_version: 5 } }),
      json(200, { version: 5, elements: [el("a"), el("s")] }),
      json(200, { version: 6 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a"), el("m")]);
    await h.sync.flushNow(); // 409, reload, merge schedules a save
    mock.timers.tick(2000);
    await settle();
    const last = h.calls.at(-1)!;
    assert.equal(last.body?.base_version, 5);
    assert.deepEqual(last.body?.elements, [el("m")]);
    assert.equal((last.body as { delta?: boolean }).delta, true);
  });

  // Both tabs bumped x to version 6 from 5; the server copy (nonce 20) is the other tab's edit.
  const tieHarness = () =>
    harness([
      json(200, { version: 5, elements: [el("x", 5, { versionNonce: 20 })] }),
      json(409, { detail: { current_version: 6 } }),
      json(200, { version: 6, elements: [el("x", 6, { versionNonce: 20, x: 100 })] }),
      json(200, { version: 7 }),
    ]);

  it("a local delete that wins a version tie is saved", async () => {
    const h = tieHarness();
    await h.sync.load();
    h.sync.notify([el("x", 6, { versionNonce: 10, isDeleted: true })]);
    await h.sync.flushNow(); // 409, reload: the tie is won locally, so a save must follow
    mock.timers.tick(2000);
    await settle();
    const put = h.calls.filter((c) => c.method === "PUT").at(-1)!;
    assert.equal(put.body?.base_version, 6);
    assert.equal(put.body?.elements.find((e) => e.id === "x")?.isDeleted, true);
  });

  it("a local edit that loses a tie is reported, and the server copy is kept", async () => {
    const h = tieHarness();
    await h.sync.load();
    h.sync.notify([el("x", 6, { versionNonce: 30, isDeleted: true })]);
    await h.sync.flushNow();
    assert.match(h.details.at(-1) ?? "", /1 of your edits/);
    assert.equal(h.reloads.at(-1)?.find((e) => e.id === "x")?.x, 100);
  });
});

describe("SceneSync idempotent saves (INK-083)", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());
  const puts = (h: ReturnType<typeof harness>) => h.calls.filter((c) => c.method === "PUT");

  it("resends the identical request under the same key after a network error", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      new TypeError("fetch failed"),
      json(200, { version: 2 }),
      json(200, { version: 3 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    h.sync.notify([el("a", 1), el("b", 1)]); // newer edit between attempts
    mock.timers.tick(2000);
    await settle();
    const [first, retry] = puts(h);
    assert.ok(first.key);
    assert.equal(retry.key, first.key);
    assert.equal(retry.raw, first.raw);
    mock.timers.tick(1500);
    await settle();
    const third = puts(h)[2];
    assert.notEqual(third.key, first.key);
    assert.equal(third.body?.base_version, 2);
  });

  it("uses a new seq for each new save, same tab prefix", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(200, { version: 2 }),
      json(200, { version: 3 }),
    ]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    await h.sync.flushNow();
    h.sync.notify([el("a", 2)]);
    await h.sync.flushNow();
    const [p1, p2] = puts(h);
    assert.notEqual(p1.key, p2.key);
    assert.equal(p1.key!.split(":")[0], p2.key!.split(":")[0]);
  });

  it("treats a 200 replay as saved, not a conflict", async () => {
    const h = harness([json(200, { version: 1, elements: [] }), new TypeError("x"), json(200, { version: 2 })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    mock.timers.tick(2000);
    await settle();
    assert.equal(h.states.at(-1), "saved");
    assert.ok(!h.states.includes("conflict"));
  });

  it("sends no second PUT while one is in flight", async () => {
    const d = deferred();
    const h = harness([json(200, { version: 1, elements: [] }), d.next, json(200, { version: 3 })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    mock.timers.tick(1500);
    await settle();
    h.sync.notify([el("a", 2)]);
    mock.timers.tick(5000);
    void h.sync.flushNow();
    await settle();
    assert.equal(puts(h).length, 1);
    d.release(json(200, { version: 2 }));
    await settle();
    await settle();
    assert.equal(puts(h).length, 2);
  });

  it("gives every PUT a timeout signal", async () => {
    const h = harness([json(200, { version: 1, elements: [] }), json(200, { version: 2 })]);
    await h.sync.load();
    h.sync.notify([el("a", 1)]);
    await h.sync.flushNow();
    assert.ok(puts(h)[0].signal);
  });

  for (const [lw, text] of [
    [{ tab: "x", same_ip: false }, /^Another device saved first/],
    [{ tab: "x", same_ip: true }, /^Another tab saved first/],
    [undefined, /^Another tab saved first/],
  ] as const) {
    it(`words the 409 notice for last_writer ${JSON.stringify(lw)}`, async () => {
      const h = harness([
        json(200, { version: 1, elements: [] }),
        json(409, { detail: { current_version: 2, last_writer: lw } }),
        json(200, { version: 2, elements: [el("z", 1)] }),
      ]);
      await h.sync.load();
      h.sync.notify([el("a", 1)]);
      await h.sync.flushNow();
      assert.match(h.details.filter((d) => d?.includes("saved first")).at(0) ?? "", text);
      assert.match(h.details.at(-1) ?? "", text);
    });
  }
});

// INK-174 (decision 0073): notify runs on every Excalidraw onChange, so an unchanged scene must cost
// no allocation. Derived as 3 times the measured median of 5 batches of 2000 unchanged notifies over
// 640 elements with the typed-array comparison (10.5 ms on the dev laptop, about 5 microseconds a
// call); the string signature it replaced took 68 to 80 ms, so the test fails if it comes back.
const NOTIFY_BUDGET_MS_PER_2000 = 30;

describe("SceneSync.notify cost and exactness (INK-174)", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());
  const scene = (n: number) => Array.from({ length: n }, (_, i) => el(`e${i}`, 1));
  const loaded = async (elements: SceneElement[]) => {
    const h = harness([json(200, { version: 1, elements }), json(200, { version: 2 }), json(200, { version: 3 })]);
    await h.sync.load();
    return h;
  };

  it("an unchanged list is not a change and emits no second dirty", async () => {
    const h = await loaded([]);
    const els = [el("a"), el("b")];
    assert.equal(h.sync.notify(els), true);
    assert.equal(h.sync.notify(els), false);
    assert.equal(h.states.filter((s) => s === "dirty").length, 1);
  });

  it("a bumped version is a change, including in-place mutation of the same object", async () => {
    const h = await loaded([el("a")]);
    const a = el("a");
    assert.equal(h.sync.notify([a]), false); // same as loaded
    a.version = 2; // Excalidraw mutates the stroke it is drawing in place
    assert.equal(h.sync.notify([a]), true);
    a.version = 3;
    assert.equal(h.sync.notify([a]), true); // while pending, compared with the newest known state
    await h.sync.flushNow();
    a.version = 4; // after a save
    assert.equal(h.sync.notify([a]), true);
  });

  it("a NaN version equals itself: an unchanged list never counts as a change (no re-save loop)", async () => {
    const h = await loaded([]);
    const els = [el("a", Number.NaN)];
    assert.equal(h.sync.notify(els), true);
    assert.equal(h.sync.notify(els), false);
    await h.sync.flushNow(); // sameSig(pending, sent) must also hold, or the save would stay pending
    assert.equal(h.sync.notify(els), false);
    assert.equal(h.sync.settledVersion(), 2);
  });

  it("a reorder, or the same version under another id, is a change", async () => {
    const h = await loaded([el("a"), el("b")]);
    assert.equal(h.sync.notify([el("b"), el("a")]), true);
    const h2 = await loaded([el("a"), el("b")]);
    assert.equal(h2.sync.notify([el("a"), el("c")]), true);
  });

  it("going back to the last saved scene while a save is pending is a change", async () => {
    const h = await loaded([el("a", 1)]);
    assert.equal(h.sync.notify([el("a", 2)]), true);
    assert.equal(h.sync.notify([el("a", 1)]), true); // an undo of an unsaved edit still has to be saved
  });

  it("is not settled while a change is pending", async () => {
    const h = await loaded([el("a")]);
    assert.equal(h.sync.settledVersion(), 1);
    h.sync.notify([el("a"), el("m")]);
    assert.equal(h.sync.settledVersion(), null);
  });

  it(`costs under ${NOTIFY_BUDGET_MS_PER_2000} ms for 2000 unchanged notifies of 640 elements`, async () => {
    const els = scene(640);
    const h = await loaded(els);
    const times: number[] = [];
    for (let batch = 0; batch < 5; batch++) {
      const t = performance.now();
      for (let i = 0; i < 2000; i++) h.sync.notify(els);
      times.push(performance.now() - t);
    }
    times.sort((a, b) => a - b);
    assert.ok(times[2] < NOTIFY_BUDGET_MS_PER_2000, `median ${times[2].toFixed(2)} ms`);
  });
});
