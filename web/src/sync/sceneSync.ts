// Framework-free load/autosave for one canvas. App.tsx wires it to Excalidraw's onChange.
// INK-113 (decision 0088): every changed element version goes to the device journal (IndexedDB) first,
// then a sender ships the unacknowledged ones with overlapping requests. The server merges every save
// element by element (decision 0080) and answers with the `newer` elements that beat ours (applyNewer).

import { isDraftTagged } from "../drafts/drafts.ts";
import type { LoadClock } from "./loadClock.ts";
import { lastResource, netParts, record, serverParts } from "../lib/timing.ts";
import { RISK_LABEL } from "../lib/status.ts";
import { entryKey, type Entry, type Journal } from "./journal.ts";
import { winsOver } from "./mergeRule.ts";
import { Sender } from "./sender.ts";

export interface SceneElement {
  id: string;
  version: number;
  [key: string]: unknown;
}

export type SaveState = "loading" | "saved" | "dirty" | "saving" | "retry" | "error";

export interface SyncOptions {
  documentId: string;
  /** Wait after the last change before it is written to the journal (default 50 ms). */
  journalMs?: number;
  fetchFn?: typeof fetch;
  clock?: LoadClock;
  /** null: memory-only mode (no IndexedDB), the bar says so. */
  journal: Journal | null;
  now?: () => number;
  onState: (state: SaveState, detail?: string) => void;
  onReload: (elements: SceneElement[]) => void;
}

const versions = (els: readonly SceneElement[]) => new Map(els.map((e) => [e.id, e.version]));

/** The elements to send for a save: only those changed since `baseline`, or null for a full
 *  save (no baseline, or an element the server holds is gone from the list, which a delta
 *  cannot express, or nothing would be saved by sending less). */
export function deltaFor(
  baseline: ReadonlyMap<string, number> | null,
  els: readonly SceneElement[],
): SceneElement[] | null {
  if (!baseline) return null;
  const ids = new Set(els.map((e) => e.id));
  for (const id of baseline.keys()) if (!ids.has(id)) return null;
  const changed = els.filter((e) => baseline.get(e.id) !== e.version);
  return changed.length < els.length ? changed : null;
}

const KEEPALIVE_MAX = 60_000;
const OLD_AFTER_MS = 60_000; // an unacknowledged entry this old turns the quiet bar grey
const MAX_WAIT_MS = 500; // longest a change waits for the journal while edits keep coming
const KEEP_ACKED_MS = 7 * 864e5;

/** A 4xx other than 429: the body would be rejected again, so it is not retried. */
class Rejected extends Error {
  status: number;
  constructor(status: number) {
    super(`Save rejected (${status})`);
    this.status = status;
  }
}

// Two element lists are "the same" if every element has the same id and version, in the same order.
// notify() runs on every Excalidraw onChange (every pen point and pan frame), so the common answer
// "nothing changed" is a loop over ids and versions that allocates nothing (INK-174, decision 0073).
interface Sig {
  ids: string[];
  vers: Float64Array;
}
const EMPTY_SIG: Sig = { ids: [], vers: new Float64Array(0) };
const sigOf = (els: readonly SceneElement[]): Sig => {
  const n = els.length;
  const ids = new Array<string>(n);
  const vers = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    ids[i] = els[i].id;
    vers[i] = els[i].version;
  }
  return { ids, vers };
};
const sigMatches = (s: Sig, els: readonly SceneElement[]): boolean => {
  if (s.ids.length !== els.length) return false;
  for (let i = 0; i < els.length; i++) if (!Object.is(els[i].version, s.vers[i]) || els[i].id !== s.ids[i]) return false; // Object.is: NaN equals itself
  return true;
};

/** Show the elements a save answer says beat ours (decision 0080). A newer copy replaces the local one in
 *  place if it wins by the shared rule; an unknown id is appended; a tombstone stub (no `type`) only sets
 *  the delete on the shape we have, and is ignored for an id we never had. */
export function applyNewer(local: readonly SceneElement[], newer: readonly SceneElement[]): SceneElement[] {
  const byId = new Map(local.map((e) => [e.id, e]));
  const added: SceneElement[] = [];
  for (const n of newer) {
    const mine = byId.get(n.id);
    if (!mine) {
      if (n.type !== undefined) added.push(n); // a stub for an unknown id: nothing to show
      continue;
    }
    if (winsOver(n, mine)) byId.set(n.id, n.type === undefined ? { ...mine, ...n } : n); // stub: keep the shape, set the delete
  }
  return [...local.map((e) => byId.get(e.id)!), ...added];
}

function liveIds(elements: readonly SceneElement[]): Set<string> {
  return new Set(elements.filter((e) => !e.isDeleted).map((e) => e.id));
}

export class SceneSync {
  private readonly o: SyncOptions;
  private readonly fetchFn: typeof fetch;
  private version = 0;
  private loadSeq = 0;
  private lastSig: Sig = EMPTY_SIG;
  private rawSig: Sig = EMPTY_SIG; // the last unfiltered input, so an unchanged notify skips the draft scan
  private disposed = false;
  private loaded = false;
  /** The last load got a 404: no canvas has this id (a network error or a 5xx leaves it false). */
  notFound = false;
  /** True when a journal is open and no write to it failed. */
  journalOk: boolean;
  private state: SaveState = "loading";
  // The most recent scene Excalidraw reported (or the loaded one).
  private latest: readonly SceneElement[] | null = null;
  // Ids of the live elements the server holds; hasSaved also needs them out of `unacked`.
  private savedIds = new Set<string>();
  // id -> version of every element already queued for, or written to, the journal.
  private journaled = new Map<string, number>();
  private queue = new Map<string, SceneElement>(); // changed, not yet journaled
  private unacked = new Map<string, Entry>(); // latest unacknowledged entry per id (mirror of the journal)
  private timer: ReturnType<typeof setTimeout> | null = null;
  private maxTimer: ReturnType<typeof setTimeout> | null = null;
  private writing: Promise<void> = Promise.resolve();
  private keepalive = false;
  private lastMs = 0;
  readonly sender: Sender;
  // LAN HTTP is not a secure context, so crypto.randomUUID may be missing.
  readonly tabId = Math.random().toString(36).slice(2, 10);
  private seq = 0;

  constructor(options: SyncOptions) {
    this.o = options;
    this.journalOk = options.journal !== null;
    this.fetchFn = options.fetchFn ?? ((...a) => fetch(...a));
    this.sender = new Sender({
      unacked: () => [...this.unacked.values()],
      send: (els, signal) => this.send(els, signal),
      ack: (sent) => this.ack(sent),
      fail: (err) => this.fail(err),
      now: options.now,
    });
  }

  private now() {
    return (this.o.now ?? Date.now)();
  }

  // A disposed instance (React StrictMode runs effects twice) must not touch the shared badge.
  private emit(state: SaveState, detail?: string) {
    this.state = state;
    if (!this.disposed) this.o.onState(state, detail);
  }

  /** With a working journal ink is safe, so the bar stays quiet until an entry has waited too long. */
  private refresh(checkAge = false) {
    if (this.disposed) return;
    const work = this.queue.size > 0 || this.unacked.size > 0 || this.timer !== null;
    if (this.o.journal && this.journalOk) {
      const oldest = checkAge ? this.sender.oldestUnackedAt() : null;
      if (oldest !== null && this.now() - oldest > OLD_AFTER_MS) this.emit("retry", "Offline, retrying");
      else if (this.state !== "saved") this.emit("saved");
    } else if (this.sender.busy > 0) this.emit("saving");
    else if (this.sender.failing && this.unacked.size > 0) this.emit("retry", "Offline, retrying");
    else if (work) this.emit("dirty");
    else if (this.state !== "saved") this.emit("saved");
  }

  private url() {
    return `/documents/${encodeURIComponent(this.o.documentId)}/scene`;
  }

  /** The canvas to open: the device copy if there is one (no request), else the saved scene. null (state "error") if the canvas does not exist or the API is down. */
  async load(): Promise<SceneElement[] | null> {
    this.emit("loading");
    this.notFound = false;
    const t0 = performance.now();
    const j = this.o.journal;
    const doc = this.o.documentId;
    let local: Awaited<ReturnType<Journal["load"]>> = null;
    if (j) {
      try {
        local = await j.load(doc);
      } catch {
        this.journalOk = false;
      }
    }
    if (local && j) {
      this.version = this.loadSeq = local.seq;
      for (const e of await j.unacked(doc).catch(() => [])) this.unacked.set(e.id, e);
      this.adopt(local.elements);
      this.savedIds = new Set([...liveIds(local.elements)].filter((id) => !this.unacked.has(id)));
      this.loaded = true;
      record("scene.load", performance.now() - t0, { elements: local.elements.length, local: 1 });
      this.emit("saved");
      void j.prune(doc, this.now() - KEEP_ACKED_MS).catch(() => {});
      return local.elements;
    }
    try {
      const r = await this.fetchFn(this.url());
      this.o.clock?.mark("fetch"); // time to the response headers
      if (!r.ok) {
        this.notFound = r.status === 404;
        this.emit("error", r.status === 404 ? "Unknown canvas" : `Load failed (${r.status})`);
        return null;
      }
      const body = (await r.json()) as { version: number; elements: SceneElement[] };
      this.o.clock?.mark("parse", { elements: body.elements.length }); // body download + parse
      this.version = this.loadSeq = body.version;
      this.adopt(body.elements);
      this.savedIds = liveIds(body.elements);
      this.loaded = true;
      record("scene.load", performance.now() - t0, { elements: body.elements.length });
      await this.writeSnapshot(body.version, body.elements);
      this.emit("saved");
      return body.elements;
    } catch {
      this.emit("error", "Cannot reach the Inkbridge API");
      return null;
    }
  }

  private adopt(elements: readonly SceneElement[]) {
    this.lastSig = sigOf(elements);
    this.rawSig = EMPTY_SIG;
    this.journaled = versions(elements);
    this.latest ??= elements; // a remote delta before the first onChange still needs the whole scene
  }

  private async writeSnapshot(seq: number, elements: readonly SceneElement[]) {
    const j = this.o.journal;
    if (!j || !this.journalOk) return;
    try {
      await j.saveSnapshot(this.o.documentId, seq, elements, this.now());
      await j.prune(this.o.documentId, this.now() - KEEP_ACKED_MS);
    } catch {
      this.journalOk = false;
    }
  }

  /** Rewrite the device snapshot from the canvas, with the newest seq the server confirmed to us (never the answer to our own save). */
  async snapshot(seq: number) {
    if (this.latest) await this.writeSnapshot(seq, this.latest);
  }

  /** Call from onChange with every element including deleted ones. Cheap when nothing changed.
   *  Returns true if the elements really changed. */
  notify(elements: readonly SceneElement[]): boolean {
    // Before the scene is loaded the canvas is not the saved scene: saving it would overwrite it.
    if (this.disposed || !this.loaded) return false;
    // Unchanged input (the common case) skips the draft scan: its answer cannot differ.
    if (sigMatches(this.rawSig, elements)) return false;
    this.rawSig = sigOf(elements);
    // Drafts live only in the placed-op list, never in the saved scene (INK-115). Soft-deleted ones too.
    if (elements.some((e) => isDraftTagged(e))) elements = elements.filter((e) => !isDraftTagged(e));
    this.latest = elements;
    if (sigMatches(this.lastSig, elements)) return false;
    this.lastSig = sigOf(elements);
    for (const e of elements) if (!Object.is(this.journaled.get(e.id), e.version)) this.queue.set(e.id, e);
    if (this.queue.size > 0) {
      this.refresh();
      this.schedule();
    }
    return true;
  }

  /** The stored scene version the canvas matches exactly; null before load or while edits are
   *  unsaved or being saved (crop sync renders only a saved scene, decision 0015). */
  settledVersion(): number | null {
    const idle = this.queue.size === 0 && this.unacked.size === 0 && this.timer === null && this.maxTimer === null && this.sender.busy === 0;
    return this.loaded && !this.disposed && idle ? this.version : null;
  }

  /** Send now (keepalive for a small body) from the in-memory queue, journal in parallel, wait for the requests on the wire.
   *  The send never waits for IndexedDB: on pagehide it may not get the time. */
  async flushNow() {
    if (!this.loaded) return;
    const written = this.enqueueWrite(true);
    this.keepalive = true;
    try {
      this.sender.kick();
      await written;
      this.sender.kick(); // entries a timer write was still persisting
    } finally {
      this.keepalive = false;
    }
    await this.sender.drain();
  }

  /** True once the server holds every listed element (an op is acked only after its drafts are). */
  hasSaved(ids: readonly string[]): boolean {
    return ids.every((id) => this.savedIds.has(id) && !this.unacked.has(id));
  }

  /** Leave the canvas: journal and send what is still unsent, then stop. dispose() alone would drop the last edit. */
  async close() {
    try {
      await this.flushNow();
    } finally {
      this.dispose();
    }
  }

  dispose() {
    this.disposed = true;
    this.clearTimers();
    this.sender.stop();
  }

  // Trailing 50 ms, but at least every MAX_WAIT_MS while edits keep coming: a long stroke is journaled in pieces.
  private schedule() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.enqueueWrite(), this.o.journalMs ?? 50);
    this.maxTimer ??= setTimeout(() => void this.enqueueWrite(), MAX_WAIT_MS);
  }

  private clearTimers() {
    if (this.timer) clearTimeout(this.timer);
    if (this.maxTimer) clearTimeout(this.maxTimer);
    this.timer = this.maxTimer = null;
  }

  /** Take the queue now. `early`: the entries go to the sender's mirror before the journal write finishes. */
  private enqueueWrite(early = false): Promise<void> {
    this.clearTimers();
    if (this.queue.size === 0) return this.writing;
    // Excalidraw mutates element objects in place: journal and send a copy of this version.
    const els = [...this.queue.values()].map((e) => ({ ...e }));
    this.queue.clear();
    const at = this.now();
    for (const e of els) this.journaled.set(e.id, e.version);
    if (early) this.expose(els, at);
    return (this.writing = this.writing.then(() => this.persist(els, at, early)));
  }

  private expose(els: readonly SceneElement[], at: number) {
    for (const el of els) {
      this.unacked.set(el.id, { k: entryKey(this.o.documentId, el.id, el.version), doc: this.o.documentId, id: el.id, version: el.version, el, acked: false, at });
    }
  }

  private async persist(els: readonly SceneElement[], at: number, early: boolean) {
    let failed = false;
    if (this.o.journal && this.journalOk) {
      try {
        await this.o.journal.put(this.o.documentId, els, at);
      } catch {
        failed = true;
        this.journalOk = false;
      }
    }
    if (!early) this.expose(els, at);
    if (failed) this.emit("error", RISK_LABEL);
    else this.refresh(true);
  }

  private async send(els: SceneElement[], signal: AbortSignal) {
    const body = JSON.stringify({ base_version: this.version, elements: els, delta: true });
    const t0 = performance.now();
    this.refresh();
    const r = await this.fetchFn(this.url(), {
      method: "PUT",
      headers: { "content-type": "application/json", "x-inkbridge-save": `${this.tabId}:${++this.seq}` },
      body,
      signal,
      // On page hide, keepalive lets the save outlive the page; browsers cap it at 64 KiB.
      keepalive: this.keepalive && body.length < KEEPALIVE_MAX,
    });
    if (!r.ok) {
      if (r.status >= 400 && r.status < 500 && r.status !== 429) {
        // Out of the mirror so it is not resent; the journal keeps it unacknowledged.
        for (const e of els) if (this.unacked.get(e.id)?.version === e.version) this.unacked.delete(e.id);
        throw new Rejected(r.status);
      }
      throw new Error(`save failed (${r.status})`);
    }
    const saved = (await r.json()) as { version: number; newer?: SceneElement[]; timing?: Record<string, number> };
    this.version = Math.max(this.version, saved.version);
    this.lastMs = Math.round(performance.now() - t0);
    record("scene.save", this.lastMs, {
      elements: this.latest?.length ?? els.length,
      sent: els.length,
      bytes: body.length,
      ...serverParts(saved.timing),
      ...netParts(lastResource(this.url(), t0)),
    });
    if (saved.newer?.length) this.applyNewerAnswer(saved.newer);
  }

  private ack(sent: Entry[]) {
    for (const e of sent) {
      if (this.unacked.get(e.id)?.k === e.k) this.unacked.delete(e.id);
      if (e.el.isDeleted) this.savedIds.delete(e.id);
      else this.savedIds.add(e.id);
    }
    void this.o.journal?.markAcked(sent.map((e) => e.k)).catch(() => {});
    if (this.settledVersion() !== null) this.emit("saved", `${this.lastMs} ms`);
    else this.refresh(true);
  }

  private fail(err: unknown) {
    if (err instanceof Rejected) this.emit("error", `Save rejected (${err.status}); changes are not saved yet`);
    else this.refresh(true);
  }

  get loadedSeq() {
    return this.loadSeq;
  }

  /** Show elements another device wrote (scene.delta). They count as journaled, so they are not saved back. */
  applyRemote(remote: readonly SceneElement[]) {
    if (this.disposed || !this.loaded || remote.length === 0) return;
    this.applyNewerAnswer(remote);
  }

  // The server kept elements that beat ours (another device's ink, or a higher version). Show them
  // without a conflict: the canvas reloads with them, and what we have drawn since stays journaled.
  private applyNewerAnswer(newer: readonly SceneElement[]) {
    const base = this.latest ?? [];
    const mine = new Map(base.map((e) => [e.id, e]));
    const merged = applyNewer(base, newer);
    for (const n of newer) {
      const local = mine.get(n.id);
      if (!local || !winsOver(local, n)) this.journaled.set(n.id, n.version); // a local copy that still wins is already journaled
    }
    const shown = merged.length !== base.length || merged.some((e, i) => e !== base[i]);
    if (!shown || this.disposed) return;
    this.latest = merged;
    this.lastSig = sigOf(merged);
    this.rawSig = EMPTY_SIG;
    this.o.onReload(merged);
  }
}
