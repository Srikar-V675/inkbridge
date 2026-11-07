import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import type { Entry } from "../src/sync/journal.ts";
import { Sender } from "../src/sync/sender.ts";

const ent = (id: string, version: number, at = 0): Entry => ({
  k: `${id}@${version}`, doc: "d", id, version, el: { id, version }, acked: false, at,
});
const settle = () => new Promise((r) => setImmediate(r));

function rig() {
  let clock = 0;
  const mirror = new Map<string, Entry>();
  const sends: Array<{ ids: string[]; signal: AbortSignal; ok: () => void; no: (e: Error) => void }> = [];
  const acked: string[][] = [];
  const failed: unknown[] = [];
  const sender = new Sender({
    now: () => clock,
    unacked: () => [...mirror.values()],
    send: (els, signal) =>
      new Promise<void>((ok, no) => sends.push({ ids: els.map((e) => `${e.id}@${e.version}`), signal, ok, no })),
    ack: (sent) => {
      acked.push(sent.map((e) => e.k));
      for (const e of sent) if (mirror.get(e.id)?.k === e.k) mirror.delete(e.id);
    },
    fail: (e) => void failed.push(e),
  });
  const put = (e: Entry) => void mirror.set(e.id, e);
  return { sender, sends, acked, failed, put, mirror, at: (t: number) => void (clock = t) };
}

describe("Sender", () => {
  beforeEach(() => mock.timers.enable({ apis: ["setTimeout"] }));
  afterEach(() => mock.timers.reset());

  it("sends overlapping batches and never the same version twice", async () => {
    const r = rig();
    r.put(ent("A", 1));
    r.sender.tick();
    r.sender.tick(); // nothing changed: nothing sent
    assert.equal(r.sends.length, 1);
    r.put(ent("A", 2));
    r.put(ent("B", 1));
    r.sender.tick();
    assert.equal(r.sends.length, 2);
    assert.deepEqual(r.sends[1].ids, ["A@2", "B@1"]);
  });

  it("acks exactly what a request carried", async () => {
    const r = rig();
    r.put(ent("A", 1));
    r.sender.tick();
    r.put(ent("A", 2));
    r.sender.tick();
    r.sends[0].ok();
    await settle();
    assert.deepEqual(r.acked, [["A@1"]]);
    assert.equal(r.mirror.get("A")?.k, "A@2"); // A@2 is still unacked
    r.sends[1].ok();
    await settle();
    assert.equal(r.mirror.size, 0);
  });

  it("backs off 1 s, 2 s, ... after a failure, resends, and resets on success; kick ignores it", async () => {
    const r = rig();
    r.put(ent("A", 1));
    r.sender.tick();
    r.sends[0].no(new Error("offline"));
    await settle();
    assert.equal(r.failed.length, 1);
    r.at(999);
    r.sender.tick();
    assert.equal(r.sends.length, 1); // inside the backoff
    r.at(1000);
    r.sender.tick();
    assert.equal(r.sends.length, 2);
    r.sends[1].no(new Error("offline"));
    await settle();
    r.at(2500); // second failure: 2 s
    r.sender.tick();
    assert.equal(r.sends.length, 2);
    r.sender.kick();
    assert.equal(r.sends.length, 3);
    r.sends[2].ok();
    await settle();
    assert.equal(r.sender.failing, false);
    r.put(ent("A", 2));
    r.sender.tick();
    r.sends[3].no(new Error("x"));
    await settle();
    r.at(3500); // backoff is back to 1 s
    r.sender.tick();
    assert.equal(r.sends.length, 5);
  });

  it("aborts a send that ignores its signal after 8 s and reports a failure", async () => {
    const r = rig();
    r.put(ent("A", 1));
    r.sender.tick();
    mock.timers.tick(7999);
    assert.equal(r.sends[0].signal.aborted, false);
    mock.timers.tick(1);
    assert.equal(r.sends[0].signal.aborted, true);
    await settle();
    assert.equal(r.failed.length, 1);
    assert.equal(r.sender.busy, 0);
  });

  it("oldestUnackedAt is the oldest entry still unacked, or null", () => {
    const r = rig();
    assert.equal(r.sender.oldestUnackedAt(), null);
    r.put(ent("A", 1, 50));
    r.put(ent("B", 1, 20));
    assert.equal(r.sender.oldestUnackedAt(), 20);
  });

  it("start() ticks on an interval and stop() ends it", () => {
    mock.timers.reset();
    mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
    const r = rig();
    r.put(ent("A", 1));
    r.sender.start();
    mock.timers.tick(1000);
    assert.equal(r.sends.length, 1);
    r.sender.stop();
    r.put(ent("B", 1));
    mock.timers.tick(5000);
    assert.equal(r.sends.length, 1);
  });
});
