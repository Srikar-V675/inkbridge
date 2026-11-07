// Device journal (INK-113, decision 0088): every changed element version is written to IndexedDB before
// any request, so ink survives a reload or a dead network. Framework-free; App wires it to SceneSync.
import { winsOver } from "./mergeRule.ts";
import type { SceneElement } from "./sceneSync.ts";

export interface Entry { k: string; doc: string; id: string; version: number; el: SceneElement; acked: boolean; at: number }
export interface Snapshot { doc: string; seq: number; elements: SceneElement[]; at: number }
export interface Journal {
  put(doc: string, els: readonly SceneElement[], now: number): Promise<void>; // acked=false
  unacked(doc: string): Promise<Entry[]>; // latest version per id, only if that version is not acked
  markAcked(keys: readonly string[]): Promise<void>;
  load(doc: string): Promise<{ seq: number; elements: SceneElement[] } | null>; // snapshot + entries; null if neither
  saveSnapshot(doc: string, seq: number, elements: readonly SceneElement[], now: number): Promise<void>;
  prune(doc: string, olderThan: number): Promise<void>; // acked entries only
}

export const entryKey = (doc: string, id: string, version: number) => `${doc}\u0000${id}\u0000${version}`;

const toEntries = (doc: string, els: readonly SceneElement[], now: number): Entry[] =>
  els.map((el) => ({ k: entryKey(doc, el.id, el.version), doc, id: el.id, version: el.version, el: { ...el }, acked: false, at: now }));

/** The newest entry per id (higher version wins; same version keeps the later one). */
function latestPerId(entries: readonly Entry[]): Entry[] {
  const m = new Map<string, Entry>();
  for (const e of entries) {
    const c = m.get(e.id);
    if (!c || e.version >= c.version) m.set(e.id, e);
  }
  return [...m.values()];
}

function merge(snap: Snapshot | undefined, entries: readonly Entry[]) {
  if (!snap && entries.length === 0) return null;
  const byId = new Map((snap?.elements ?? []).map((e) => [e.id, e]));
  // Oldest first, so ids the snapshot lacks keep the order they were drawn in.
  for (const { el } of [...entries].sort((a, b) => a.at - b.at)) {
    const cur = byId.get(el.id);
    if (!cur || winsOver(el, cur)) byId.set(el.id, el);
  }
  return { seq: snap?.seq ?? 0, elements: [...byId.values()] };
}

export class MemoryJournal implements Journal {
  private entries = new Map<string, Entry>();
  private snaps = new Map<string, Snapshot>();
  async put(doc: string, els: readonly SceneElement[], now: number) {
    for (const e of toEntries(doc, els, now)) this.entries.set(e.k, e);
  }
  private of(doc: string) {
    return [...this.entries.values()].filter((e) => e.doc === doc);
  }
  async unacked(doc: string) {
    return latestPerId(this.of(doc)).filter((e) => !e.acked);
  }
  async markAcked(keys: readonly string[]) {
    for (const k of keys) {
      const e = this.entries.get(k);
      if (e) e.acked = true;
    }
  }
  async load(doc: string) {
    return merge(this.snaps.get(doc), this.of(doc));
  }
  async saveSnapshot(doc: string, seq: number, elements: readonly SceneElement[], now: number) {
    this.snaps.set(doc, { doc, seq, elements: [...elements], at: now });
  }
  async prune(doc: string, olderThan: number) {
    for (const e of this.of(doc)) if (e.acked && e.at < olderThan) this.entries.delete(e.k);
  }
}

const req = <T>(r: IDBRequest<T>) =>
  new Promise<T>((ok, bad) => {
    r.onsuccess = () => ok(r.result);
    r.onerror = () => bad(r.error);
  });
const done = (tx: IDBTransaction) =>
  new Promise<void>((ok, bad) => {
    tx.oncomplete = () => ok();
    tx.onerror = tx.onabort = () => bad(tx.error);
  });

class IdbJournal implements Journal {
  private db: IDBDatabase;
  constructor(db: IDBDatabase) {
    this.db = db;
  }
  // shortcut: reads every entry and filters by document; add a `doc` index if the journal grows past a few 10k rows.
  private async all(doc: string) {
    const rows = (await req(this.db.transaction("entries").objectStore("entries").getAll())) as Entry[];
    return rows.filter((e) => e.doc === doc);
  }
  async put(doc: string, els: readonly SceneElement[], now: number) {
    const tx = this.db.transaction("entries", "readwrite");
    const s = tx.objectStore("entries");
    for (const e of toEntries(doc, els, now)) s.put(e);
    await done(tx);
  }
  async unacked(doc: string) {
    return latestPerId(await this.all(doc)).filter((e) => !e.acked);
  }
  async markAcked(keys: readonly string[]) {
    const tx = this.db.transaction("entries", "readwrite");
    const s = tx.objectStore("entries");
    for (const k of keys) {
      const g = s.get(k);
      g.onsuccess = () => g.result && s.put({ ...(g.result as Entry), acked: true });
    }
    await done(tx);
  }
  async load(doc: string) {
    const snap = (await req(this.db.transaction("snapshots").objectStore("snapshots").get(doc))) as Snapshot | undefined;
    return merge(snap, await this.all(doc));
  }
  async saveSnapshot(doc: string, seq: number, elements: readonly SceneElement[], now: number) {
    const tx = this.db.transaction("snapshots", "readwrite");
    tx.objectStore("snapshots").put({ doc, seq, elements: [...elements], at: now });
    await done(tx);
  }
  async prune(doc: string, olderThan: number) {
    const old = (await this.all(doc)).filter((e) => e.acked && e.at < olderThan);
    if (!old.length) return;
    const tx = this.db.transaction("entries", "readwrite");
    for (const e of old) tx.objectStore("entries").delete(e.k);
    await done(tx);
  }
}

/** Open the journal, or null for memory-only mode (no IndexedDB, open failed, or the probe did not round-trip). */
export async function openJournal(factory: IDBFactory | undefined = globalThis.indexedDB): Promise<Journal | null> {
  if (!factory) return null;
  try {
    const open = factory.open("inkbridge-journal", 1);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains("entries")) db.createObjectStore("entries", { keyPath: "k" });
      if (!db.objectStoreNames.contains("snapshots")) db.createObjectStore("snapshots", { keyPath: "doc" });
    };
    const db = await req(open);
    const tx = db.transaction("entries", "readwrite");
    tx.objectStore("entries").put({ k: "probe" });
    await done(tx);
    const got = (await req(db.transaction("entries").objectStore("entries").get("probe"))) as { k?: string } | undefined;
    const del = db.transaction("entries", "readwrite");
    del.objectStore("entries").delete("probe");
    await done(del);
    return got?.k === "probe" ? new IdbJournal(db) : null;
  } catch {
    return null;
  }
}
