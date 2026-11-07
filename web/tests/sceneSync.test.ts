import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { SceneSync, applyNewer, deltaFor, type SaveState, type SceneElement } from "../src/sync/sceneSync.ts";
import { MemoryJournal, entryKey, type Journal } from "../src/sync/journal.ts";
import { RISK_LABEL } from "../src/lib/status.ts";
import { setTimingSink, type TimingRecord } from "../src/lib/timing.ts";

const el = (id: string, version = 1, extra: Record<string, unknown> = {}): SceneElement => ({
  id,
  version,
  ...extra,
});
const settle = () => new Promise((r) => setImmediate(r));
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const DOC = "default";

type Call = { url: string; method: string; key?: string; keepalive?: boolean; signal?: AbortSignal | null; body?: { base_version: number; elements: SceneElement[]; delta?: boolean } };

function harness(
  responses: Array<Response | Error | (() => Response)>,
  opts: { journal?: Journal | null; offline?: boolean; onFetch?: (c: Call) => void } = {},
) {
  const calls: Call[] = [];
  const states: SaveState[] = [];
  const details: Array<string | undefined> = [];
  const reloads: SceneElement[][] = [];
  const journal = opts.journal === undefined ? new MemoryJournal() : opts.journal;
  const time = { now: 0 };
  const net = { down: opts.offline ?? false };
  const fetchFn = (async (url: string, init?: RequestInit) => {
    const c: Call = {
      url,
      method: init?.method ?? "GET",
      key: (init?.headers as Record<string, string> | undefined)?.["x-inkbridge-save"],
      keepalive: init?.keepalive,
      signal: init?.signal,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    };
    calls.push(c);
    opts.onFetch?.(c);
    if (net.down) throw new Error("offline");
    const next = responses.shift();
    if (!next) throw new Error("unexpected request " + url);
    if (next instanceof Error) throw next;
    return typeof next === "function" ? next() : next;
  }) as unknown as typeof fetch;
  const sync = new SceneSync({
    documentId: DOC,
    fetchFn,
    journal,
    now: () => time.now,
    onState: (s, d) => (states.push(s), details.push(d)),
    onReload: (e) => reloads.push(e),
  });
  const puts = () => calls.filter((c) => c.method === "PUT");
  /** A change, journaled after the 50 ms trailing wait. */
  const edit = async (els: SceneElement[]) => {
    const changed = sync.notify(els);
    mock.timers.tick(50);
    await settle();
    return changed;
  };
  /** One sender tick, and let the request settle. */
  const send = async () => {
    sync.sender.tick();
    await settle();
  };
  return { net, sync, calls, states, details, reloads, journal: journal as MemoryJournal, time, puts, edit, send };
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

  it("loads the scene and remembers its version", async () => {
    const h = harness([json(200, { version: 7, elements: [el("a")] })]);
    assert.deepEqual(await h.sync.load(), [el("a")]);
    assert.equal(h.calls[0].url, "/documents/default/scene");
    assert.equal(h.sync.loadedSeq, 7);
    assert.equal(h.states.at(-1), "saved");
  });

  it("reports an unknown canvas as an error, and tells it (404) from a failed load", async () => {
    const h404 = harness([json(404, { detail: "no" })]);
    assert.equal(await h404.sync.load(), null);
    assert.equal(h404.states.at(-1), "error");
    assert.equal(h404.sync.notFound, true);
    const h500 = harness([json(500, { detail: "boom" })]);
    await h500.sync.load();
    assert.equal(h500.sync.notFound, false);
    const hDown = harness([new Error("down")]);
    await hDown.sync.load();
    assert.equal(hDown.sync.notFound, false);
    assert.equal(hDown.states.at(-1), "error");
  });

  it("never journals or saves before the scene is loaded", async () => {
    const h = harness([]);
    assert.equal(h.sync.notify([el("a")]), false);
    mock.timers.tick(5000);
    await settle();
    assert.equal(h.calls.length, 0);
    assert.equal((await h.journal.unacked(DOC)).length, 0);
  });

  it("ignores onChange calls that did not change any element", async () => {
    const h = harness([json(200, { version: 1, elements: [el("a")] })]);
    await h.sync.load();
    assert.equal(h.sync.notify([el("a")]), false);
    assert.equal(h.states.filter((s) => s === "dirty").length, 0);
  });

  it("journals a change after 50 ms, before any request", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    assert.equal((await h.journal.unacked(DOC)).length, 0); // trailing: nothing mid-stroke
    mock.timers.tick(50);
    await settle();
    assert.deepEqual((await h.journal.unacked(DOC)).map((e) => e.id), ["a"]);
    assert.equal(h.puts().length, 0);
  });

  it("a hung PUT blocks neither the journal nor the next batch, and the bar stays quiet", async () => {
    const d = deferred();
    const h = harness([json(200, { version: 0, elements: [] }), d.next, json(200, { version: 2 })]);
    await h.sync.load();
    await h.edit([el("a", 1)]);
    await h.send(); // request 1 never answered
    await h.edit([el("a", 2), el("b", 1)]);
    assert.deepEqual((await h.journal.unacked(DOC)).map((e) => e.k.split("\0")[2]).sort(), ["1", "2"]);
    await h.send();
    assert.equal(h.puts().length, 2);
    assert.deepEqual(h.puts()[1].body?.elements.map((e) => `${e.id}@${e.version}`), ["a@2", "b@1"]);
    assert.ok(!h.states.includes("saving") && !h.states.includes("dirty"));
    assert.equal(h.states.at(-1), "saved");
    assert.equal(h.sync.settledVersion(), null);
  });

  it("an ack marks the entries and settles the scene; an answer with newer elements reaches onReload", async () => {
    const h = harness([
      json(200, { version: 1, elements: [el("x", 1)] }),
      json(200, { version: 3, newer: [el("x", 5, { type: "rect" })] }),
    ]);
    await h.sync.load();
    await h.edit([el("x", 2)]);
    assert.equal(h.sync.settledVersion(), null);
    await h.send();
    assert.equal((await h.journal.unacked(DOC)).length, 0);
    assert.equal(h.sync.settledVersion(), 3);
    assert.equal(h.sync.hasSaved(["x"]), true);
    assert.equal(h.reloads.length, 1);
    assert.equal(h.reloads[0].find((e) => e.id === "x")?.version, 5);
    assert.equal(h.sync.notify(h.reloads[0]), false); // the merged list is what the canvas shows now
    mock.timers.tick(5000);
    await settle();
    await h.send();
    assert.equal(h.puts().length, 1);
  });

  it("hasSaved is true only once the server acknowledged the elements", async () => {
    const h = harness([json(200, { version: 1, elements: [el("a")] }), new Error("offline"), json(200, { version: 2 })]);
    await h.sync.load();
    assert.equal(h.sync.hasSaved(["a"]), true);
    h.sync.notify([el("a"), el("op:1")]);
    await h.sync.flushNow(); // the send fails: flushNow resolves anyway
    assert.equal(h.sync.hasSaved(["op:1"]), false);
    await h.sync.flushNow();
    assert.equal(h.sync.hasSaved(["a", "op:1"]), true);
  });

  it("opens offline from the device copy: merged elements, an unsent stroke included, state saved", async () => {
    const j = new MemoryJournal();
    await j.saveSnapshot(DOC, 9, [el("a", 1), el("b", 1)], 0);
    await j.put(DOC, [el("a", 2), el("c", 1)], 1);
    await j.markAcked([entryKey(DOC, "a", 2)]);
    const h = harness([], { journal: j, offline: true });
    const got = await h.sync.load();
    assert.deepEqual(got?.map((e) => `${e.id}@${e.version}`), ["a@2", "b@1", "c@1"]);
    assert.equal(h.states.at(-1), "saved");
    assert.equal(h.calls.length, 0);
    assert.equal(h.sync.loadedSeq, 9);
    assert.equal(h.sync.hasSaved(["b"]), true);
    assert.equal(h.sync.hasSaved(["c"]), false); // c is still unsent
    await h.send(); // offline: the send fails quietly
    assert.equal(h.states.at(-1), "saved");
  });

  it("opening from the device copy makes no scene request", async () => {
    const j = new MemoryJournal();
    await j.saveSnapshot(DOC, 4, [el("a")], 0);
    const h = harness([], { journal: j });
    await h.sync.load();
    assert.equal(h.calls.length, 0);
  });

  it("with no device copy it fetches the scene, then writes the snapshot", async () => {
    const h = harness([json(200, { version: 5, elements: [el("a", 3)] })]);
    await h.sync.load();
    assert.equal(h.calls.length, 1);
    const kept = await h.journal.load(DOC);
    assert.equal(kept?.seq, 5);
    assert.deepEqual(kept?.elements.map((e) => e.version), [3]);
  });

  it("snapshot() rewrites the device copy with the seq it is given", async () => {
    const h = harness([json(200, { version: 5, elements: [el("a")] })]);
    await h.sync.load();
    await h.sync.snapshot(8);
    assert.equal((await h.journal.load(DOC))?.seq, 8);
  });

  it("turns grey (retry) only once the oldest unsent entry is 60 s old and sends keep failing", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    h.net.down = true;
    await h.edit([el("a")]);
    await h.send();
    assert.equal(h.states.at(-1), "saved");
    h.time.now = 59_000;
    h.sync.sender.kick();
    await settle();
    assert.equal(h.states.at(-1), "saved");
    h.time.now = 61_000;
    h.sync.sender.kick();
    await settle();
    assert.equal(h.states.at(-1), "retry");
  });

  it("a journal write that fails is the risk line, and journalOk says so", async () => {
    const j = new MemoryJournal();
    j.put = async () => {
      throw new Error("quota");
    };
    const h = harness([json(200, { version: 0, elements: [] })], { journal: j });
    await h.sync.load();
    assert.equal(h.sync.journalOk, true);
    await h.edit([el("a")]);
    assert.equal(h.sync.journalOk, false);
    assert.equal(h.states.at(-1), "error");
    assert.equal(h.details.at(-1), RISK_LABEL);
  });

  it("without a journal the states are dirty, saving and retry", async () => {
    const d = deferred();
    const h = harness([json(200, { version: 0, elements: [] }), d.next, new Error("offline")], { journal: null });
    await h.sync.load();
    assert.equal(h.sync.journalOk, false);
    h.sync.notify([el("a")]);
    assert.equal(h.states.at(-1), "dirty");
    mock.timers.tick(50);
    await settle();
    await h.send();
    assert.equal(h.states.at(-1), "saving");
    d.release(json(500, {}));
    await settle();
    assert.equal(h.states.at(-1), "retry");
  });

  it("sends only the changed elements as a delta, under a new key each time", async () => {
    const h = harness([json(200, { version: 1, elements: [el("a"), el("b")] }), json(200, { version: 2 }), json(200, { version: 3 })]);
    await h.sync.load();
    await h.edit([el("a"), el("b", 2), el("c")]);
    await h.send();
    const [p] = h.puts();
    assert.equal(p.body?.delta, true);
    assert.equal(p.body?.base_version, 1);
    assert.deepEqual(p.body?.elements.map((e) => e.id), ["b", "c"]);
    await h.edit([el("a"), el("b", 2), el("c", 2)]);
    await h.send();
    assert.notEqual(h.puts()[1].key, p.key);
    assert.equal(h.puts()[1].key?.split(":")[0], p.key?.split(":")[0]);
    assert.equal(h.puts()[1].body?.base_version, 2);
  });

  it("keeps pressures and simulatePressure=false in the sent body", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    await h.edit([el("s", 1, { type: "freedraw", pressures: [0.2, 0.5], simulatePressure: false })]);
    await h.send();
    const sent = h.puts()[0].body?.elements[0];
    assert.deepEqual(sent?.pressures, [0.2, 0.5]);
    assert.equal(sent?.simulatePressure, false);
  });

  it("an element mutated in place is journaled as a copy of that version", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    const a = el("a", 1, { x: 1 });
    await h.edit([a]);
    a.version = 2;
    a.x = 9;
    const [e] = await h.journal.unacked(DOC);
    assert.equal(e.el.version, 1);
    assert.equal(e.el.x, 1);
  });

  it("does not retry a 422 and says so; the journal keeps the ink unsent", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(422, { detail: "bad" })]);
    await h.sync.load();
    await h.edit([el("a")]);
    await h.send();
    assert.equal(h.states.at(-1), "error");
    assert.equal(h.details.at(-1), "Save rejected (422); changes are not saved yet");
    h.sync.sender.kick();
    await settle();
    assert.equal(h.puts().length, 1);
    assert.equal((await h.journal.unacked(DOC)).length, 1);
  });

  it("a 500 is retried after the backoff", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(500, {}), json(200, { version: 1 })]);
    await h.sync.load();
    await h.edit([el("a")]);
    await h.send();
    h.time.now = 500;
    await h.send();
    assert.equal(h.puts().length, 1); // inside the 1 s backoff
    h.time.now = 1000;
    await h.send();
    assert.equal(h.puts().length, 2);
    assert.equal(h.sync.settledVersion(), 1);
  });

  it("flushNow asks for keepalive for a small body; the interval tick does not", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 }), json(200, { version: 2 })]);
    await h.sync.load();
    await h.edit([el("a")]);
    await h.send();
    h.sync.notify([el("a"), el("b")]);
    await h.sync.flushNow();
    assert.equal(h.puts()[0].keepalive, false);
    assert.equal(h.puts()[1].keepalive, true);
  });

  it("flushNow journals pending edits at once, without waiting for the 50 ms", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })]);
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.flushNow();
    assert.equal(h.puts().length, 1);
  });

  it("a disposed instance no longer reports state", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    h.sync.dispose();
    const n = h.states.length;
    h.sync.notify([el("a")]);
    assert.equal(h.states.length, n);
  });

  it("close() writes the journal first, then makes one keepalive attempt, then disposes", async () => {
    const order: string[] = [];
    const j = new MemoryJournal();
    const put = j.put.bind(j);
    j.put = async (...a) => (order.push("journal"), put(...a));
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1 })], {
      journal: j,
      onFetch: (c) => c.method === "PUT" && order.push("fetch"),
    });
    await h.sync.load();
    h.sync.notify([el("a")]);
    await h.sync.close();
    assert.deepEqual(order, ["journal", "fetch"]);
    assert.equal(h.puts()[0].keepalive, true);
    assert.equal(h.sync.notify([el("a", 2)]), false); // disposed
  });

  it("close() with nothing to send sends nothing", async () => {
    const h = harness([json(200, { version: 1, elements: [] })]);
    await h.sync.load();
    await h.sync.close();
    assert.equal(h.puts().length, 0);
  });

  it("close() while offline leaves the ink in the journal", async () => {
    const h = harness([json(200, { version: 0, elements: [] })]);
    await h.sync.load();
    h.net.down = true;
    h.sync.notify([el("a")]);
    await h.sync.close();
    assert.equal((await h.journal.unacked(DOC)).length, 1);
  });

  it("settledVersion is the saved version only when nothing is unsent or in flight", async () => {
    const d = deferred();
    const h = harness([json(200, { version: 3, elements: [] }), d.next]);
    await h.sync.load();
    assert.equal(h.sync.settledVersion(), 3);
    await h.edit([el("a")]);
    assert.equal(h.sync.settledVersion(), null);
    await h.send();
    assert.equal(h.sync.settledVersion(), null); // in flight
    d.release(json(200, { version: 4 }));
    await settle();
    assert.equal(h.sync.settledVersion(), 4);
  });
});

describe("deltaFor (INK-075)", () => {
  it("sends the changed and new elements, or null for a full save", () => {
    const base = new Map([["a", 1], ["b", 1]]);
    assert.deepEqual(deltaFor(base, [el("a"), el("b", 2), el("c")]), [el("b", 2), el("c")]);
    assert.equal(deltaFor(base, [el("a")]), null); // an element the server holds is gone
    assert.equal(deltaFor(null, [el("a")]), null);
    assert.equal(deltaFor(base, [el("a", 2), el("b", 2)]), null); // nothing saved by sending less
  });
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

  it("an unchanged list is not a change and queues one journal write", async () => {
    const h = await loaded([]);
    const els = [el("a"), el("b")];
    assert.equal(h.sync.notify(els), true);
    assert.equal(h.sync.notify(els), false);
    mock.timers.tick(50);
    await settle();
    assert.equal((await h.journal.unacked(DOC)).length, 2);
  });

  it("a bumped version is a change, including in-place mutation of the same object", async () => {
    const h = await loaded([el("a")]);
    const a = el("a");
    assert.equal(h.sync.notify([a]), false); // same as loaded
    a.version = 2; // Excalidraw mutates the stroke it is drawing in place
    assert.equal(h.sync.notify([a]), true);
    a.version = 3;
    assert.equal(h.sync.notify([a]), true);
    await h.sync.flushNow();
    a.version = 4;
    assert.equal(h.sync.notify([a]), true);
  });

  it("a NaN version equals itself: an unchanged list never counts as a change (no re-journal loop)", async () => {
    const h = await loaded([]);
    const els = [el("a", Number.NaN)];
    assert.equal(h.sync.notify(els), true);
    assert.equal(h.sync.notify(els), false);
    await h.sync.flushNow();
    assert.equal(h.sync.notify(els), false);
    assert.equal(h.sync.settledVersion(), 2);
  });

  it("a reorder, or the same version under another id, is a change", async () => {
    const h = await loaded([el("a"), el("b")]);
    assert.equal(h.sync.notify([el("b"), el("a")]), true);
    const h2 = await loaded([el("a"), el("b")]);
    assert.equal(h2.sync.notify([el("a"), el("c")]), true);
  });

  it("going back to the loaded scene after an edit is a change", async () => {
    const h = await loaded([el("a", 1)]);
    assert.equal(h.sync.notify([el("a", 2)]), true);
    assert.equal(h.sync.notify([el("a", 1)]), true);
  });

  it("is not settled while a change is queued", async () => {
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

describe("save answers carry newer elements (INK-111, decision 0080)", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());

  it("applyNewer replaces older local copies in place, appends unknown ids and applies a stub as a delete", () => {
    const local = [el("a", 1, { x: 1 }), el("b", 1)];
    const stub = { id: "a", version: 3, versionNonce: 7, isDeleted: true };
    const out = applyNewer(local, [el("b", 4, { type: "rect", x: 9 }), el("c", 1, { type: "rect" }), stub]);
    assert.deepEqual(out, [
      { id: "a", version: 3, versionNonce: 7, isDeleted: true, x: 1 },
      el("b", 4, { type: "rect", x: 9 }),
      el("c", 1, { type: "rect" }),
    ]);
  });

  it("applyNewer ignores a newer element that does not beat the local one and a stub for an unknown id", () => {
    const local = [el("a", 5, { versionNonce: 2 })];
    const out = applyNewer(local, [el("a", 4, { type: "rect" }), el("a", 5, { type: "rect", versionNonce: 9 }), { id: "z", version: 9, isDeleted: true }]);
    assert.deepEqual(out, local);
  });

  it("a save answer without newer does not call onReload", async () => {
    const h = harness([json(200, { version: 0, elements: [] }), json(200, { version: 1, newer: [] })]);
    await h.sync.load();
    await h.edit([el("a")]);
    await h.send();
    assert.equal(h.reloads.length, 0);
  });

  it("edits made during the request survive the reload and are sent next", async () => {
    const d = deferred();
    const h = harness([json(200, { version: 1, elements: [el("x", 1)] }), d.next, json(200, { version: 4 })]);
    await h.sync.load();
    await h.edit([el("x", 2)]);
    await h.send();
    await h.edit([el("x", 3), el("y", 1)]); // drawn while the PUT is in flight
    d.release(json(200, { version: 3, newer: [el("x", 5, { type: "rect" })] }));
    await settle();
    assert.deepEqual(h.reloads.at(-1)!.map((e) => [e.id, e.version]), [["x", 5], ["y", 1]]);
    await h.send();
    // x v3 lost to the server's v5 and is never worth sending again once x v5 is shown; y goes out
    assert.ok(h.puts()[1].body?.elements.some((e) => e.id === "y"));
  });
});

describe("SceneSync.applyRemote (INK-112, decision 0087)", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());
  const loaded = async () => {
    const h = harness([json(200, { version: 4, elements: [el("a", 1, { type: "rect" }), el("b", 1, { type: "rect" })] }), json(200, { version: 5 })]);
    await h.sync.load();
    return h;
  };

  it("shows newer and new elements once, stays saved and never saves them back", async () => {
    const h = await loaded();
    h.sync.applyRemote([el("a", 3, { type: "rect", x: 7 }), el("n", 1, { type: "rect" })]);
    assert.equal(h.reloads.length, 1);
    assert.deepEqual(h.reloads[0].map((e) => [e.id, e.version]), [["a", 3], ["b", 1], ["n", 1]]);
    assert.equal(h.states.at(-1), "saved");
    h.sync.notify(h.reloads[0]);
    mock.timers.tick(5000);
    await settle();
    await h.send();
    assert.equal(h.puts().length, 0);
    assert.equal((await h.journal.unacked(DOC)).length, 0);
  });

  it("applies a tombstone stub as a delete", async () => {
    const h = await loaded();
    h.sync.applyRemote([{ id: "b", version: 5, versionNonce: 1, isDeleted: true }]);
    assert.equal(h.reloads[0].find((e) => e.id === "b")?.isDeleted, true);
  });

  it("keeps an unsaved local edit queued and sent", async () => {
    const h = await loaded();
    h.sync.notify([el("a", 2, { type: "rect" }), el("b", 1, { type: "rect" })]);
    h.sync.applyRemote([el("n", 1, { type: "rect" })]);
    assert.ok(h.reloads[0].some((e) => e.id === "a" && e.version === 2));
    await h.sync.flushNow();
    const sent = h.puts()[0];
    assert.ok(sent, "the local edit is still saved");
    assert.ok(JSON.stringify(sent.body).includes('"id":"a"'));
    assert.ok(!JSON.stringify(sent.body).includes('"id":"n"'));
  });
});
