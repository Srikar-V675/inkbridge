import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { MemoryJournal, entryKey, openJournal, type Journal } from "../src/sync/journal.ts";
import type { SceneElement } from "../src/sync/sceneSync.ts";

const el = (id: string, version = 1, extra: Record<string, unknown> = {}): SceneElement => ({ id, version, ...extra });

// A tiny in-memory IDBFactory: just the calls journal.ts makes, fired asynchronously like the real one.
function fakeIdb(opts: { corruptGet?: boolean; failOpen?: boolean } = {}) {
  const stores = new Map<string, { keyPath: string; rows: Map<string, unknown> }>();
  const later = (f: () => void) => setImmediate(f);
  function db() {
    return {
      objectStoreNames: { contains: (n: string) => stores.has(n) },
      createObjectStore: (n: string, o: { keyPath: string }) => void stores.set(n, { keyPath: o.keyPath, rows: new Map() }),
      transaction: () => {
        const tx: Record<string, unknown> = {};
        let pending = 0;
        const settle = () => {
          if (pending === 0) later(() => pending === 0 && (tx.oncomplete as () => void)?.());
        };
        const request = (run: () => unknown) => {
          const r: Record<string, unknown> = {};
          pending++;
          later(() => {
            r.result = run();
            (r.onsuccess as () => void)?.();
            pending--;
            settle();
          });
          return r;
        };
        tx.objectStore = (n: string) => {
          const s = stores.get(n)!;
          return {
            put: (v: Record<string, string>) => request(() => void s.rows.set(String(v[s.keyPath]), structuredClone(v))),
            get: (k: string) => request(() => (opts.corruptGet ? { k: "other" } : structuredClone(s.rows.get(k)))),
            getAll: () => request(() => [...s.rows.values()].map((v) => structuredClone(v))),
            delete: (k: string) => request(() => void s.rows.delete(k)),
          };
        };
        later(settle);
        return tx;
      },
    };
  }
  return {
    open: () => {
      const r: Record<string, unknown> = {};
      later(() => {
        if (opts.failOpen) return (r.onerror as () => void)();
        r.result = db();
        (r.onupgradeneeded as () => void)?.();
        (r.onsuccess as () => void)?.();
      });
      return r;
    },
  } as unknown as IDBFactory;
}

const impls: Array<[string, () => Promise<Journal>]> = [
  ["MemoryJournal", async () => new MemoryJournal()],
  ["IdbJournal", async () => (await openJournal(fakeIdb()))!],
];

for (const [name, make] of impls) {
  describe(name, () => {
    it("load merges the snapshot with entries by the merge rule", async () => {
      const j = await make();
      await j.saveSnapshot("d", 7, [el("a", 2), el("b", 5)], 1);
      await j.put("d", [el("a", 3), el("b", 4), el("c", 1)], 2);
      const got = await j.load("d");
      assert.equal(got?.seq, 7);
      assert.deepEqual(got?.elements.map((e) => [e.id, e.version]), [["a", 3], ["b", 5], ["c", 1]]);
      assert.equal(await j.load("nothing"), null);
    });

    it("unacked is the latest version per id, and markAcked flips exactly the listed keys", async () => {
      const j = await make();
      await j.put("d", [el("a", 1), el("b", 1)], 1);
      await j.put("d", [el("a", 2)], 2);
      assert.deepEqual((await j.unacked("d")).map((e) => e.k).sort(), [entryKey("d", "a", 2), entryKey("d", "b", 1)]);
      await j.markAcked([entryKey("d", "a", 2)]);
      assert.deepEqual((await j.unacked("d")).map((e) => e.k), [entryKey("d", "b", 1)]);
    });

    it("prune deletes old acked entries and never an unacked one", async () => {
      const j = await make();
      await j.put("d", [el("a", 1), el("b", 1)], 10);
      await j.markAcked([entryKey("d", "a", 1)]);
      await j.prune("d", 100);
      assert.deepEqual((await j.load("d"))?.elements.map((e) => e.id), ["b"]);
      assert.equal((await j.unacked("d")).length, 1);
    });

    it("two documents do not see each other", async () => {
      const j = await make();
      await j.put("d1", [el("a")], 1);
      await j.put("d2", [el("z")], 1);
      assert.deepEqual((await j.load("d1"))?.elements.map((e) => e.id), ["a"]);
      assert.deepEqual((await j.unacked("d2")).map((e) => e.id), ["z"]);
      await j.prune("d1", 100);
      assert.equal((await j.unacked("d2")).length, 1);
    });
  });
}

describe("openJournal", () => {
  it("is null without IndexedDB, when open throws, and when the probe reads back something else", async () => {
    assert.equal(await openJournal(undefined), null);
    assert.equal(await openJournal(fakeIdb({ failOpen: true })), null);
    assert.equal(await openJournal(fakeIdb({ corruptGet: true })), null);
    assert.ok(await openJournal(fakeIdb()));
  });
});
