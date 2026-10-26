import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { SceneSync, mergeScenes, type SaveState, type SceneElement } from "../src/sceneSync.ts";

const el = (id: string, version = 1, extra: Record<string, unknown> = {}): SceneElement => ({
  id,
  version,
  ...extra,
});
const settle = () => new Promise((r) => setImmediate(r));
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

type Call = { url: string; method: string; body?: { base_version: number; elements: SceneElement[] } };

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
    assert.deepEqual(put.body?.elements.map((e) => e.id).sort(), ["s1", "s2", "server"]);
  });

  it("mergeScenes keeps the newer version of an element and never drops a local one", () => {
    const merged = mergeScenes(
      [el("a", 2, { from: "server" }), el("b", 1)],
      [el("a", 3, { from: "local" }), el("c", 1)],
    );
    assert.deepEqual(merged.map((e) => [e.id, e.from ?? null]), [["a", "local"], ["b", null], ["c", null]]);
    assert.equal(mergeScenes([el("a", 5, { from: "server" })], [el("a", 5, { from: "local" })])[0].from, "server");
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
    assert.deepEqual(put.body?.elements.map((e) => e.id).sort(), ["s1", "s2", "server"]);
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
});
