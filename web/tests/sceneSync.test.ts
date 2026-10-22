import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { SceneSync, type SaveState, type SceneElement } from "../src/sceneSync.ts";

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
    onState: (s) => states.push(s),
    onReload: (e) => reloads.push(e),
  });
  return { sync, calls, states, reloads, stored };
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
    release(json(200, { version: 2 }));
    await settle();
    mock.timers.tick(1500);
    await settle();
    assert.equal(h.calls.filter((c) => c.method === "PUT").length, 2);
  });

  it("on 409 reloads the server scene, backs up the local edits and tells the caller", async () => {
    const h = harness([
      json(200, { version: 1, elements: [] }),
      json(409, { detail: { current_version: 9 } }),
      json(200, { version: 9, elements: [el("server", 4)] }),
    ]);
    await h.sync.load();
    h.sync.notify([el("mine", 1)]);
    mock.timers.tick(1500);
    await settle();
    assert.deepEqual(h.reloads, [[el("server", 4)]]);
    assert.equal(h.states.includes("conflict"), true);
    const backup = Object.entries(h.stored).find(([k]) => k.includes("conflict"));
    assert.ok(backup && JSON.parse(backup[1]).some((e: SceneElement) => e.id === "mine"));
    h.sync.notify([el("server", 5)]); // next save uses the reloaded version
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
});
