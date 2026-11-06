// Framework-free load/autosave for one canvas. App.tsx wires it to Excalidraw's onChange.
// Rules (tech ref 9.1 / 10.1): never block drawing, PUT with base_version, 409 means reload and merge (docs/decisions/0008).

import type { LoadClock } from "./loadClock.ts";
import { lastResource, netParts, record, serverParts } from "../lib/timing.ts";

export interface SceneElement {
  id: string;
  version: number;
  [key: string]: unknown;
}

export type SaveState = "loading" | "saved" | "dirty" | "saving" | "retry" | "conflict" | "error";

export interface SyncOptions {
  documentId: string;
  debounceMs?: number;
  fetchFn?: typeof fetch;
  clock?: LoadClock;
  storage?: Pick<Storage, "setItem">;
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
const SAVE_TIMEOUT_MS = 30_000;

// An unsent-or-unanswered save, kept whole so a retry resends the same body under the same key (INK-083).
interface SaveRequest {
  key: string;
  body: string;
  sent: readonly SceneElement[];
  sentSig: string;
  sentVersions: Map<string, number>;
  changed: SceneElement[] | null;
}

interface LastWriter {
  tab?: string;
  same_ip?: boolean;
}
const RETRY_MS = [2000, 4000, 8000, 16000, 30000];

// Two element lists are "the same" if every element has the same id and version.
const signature = (els: readonly SceneElement[]) => els.map((e) => `${e.id}:${e.version}`).join("|");

const nonce = (e: SceneElement) => (e.versionNonce as number | undefined) ?? 0;
// Excalidraw's undo and edits always bump `version` (never reuse an older number), so deltaFor stays safe.
// Not verified against a real Excalidraw run (decision 0038).
const localWins = (l: SceneElement, s: SceneElement) =>
  l.version > s.version || (l.version === s.version && nonce(l) < nonce(s));

/** Server scene plus every local element. The higher `version` wins; on a tie the lower
 *  `versionNonce` wins, the same rule Excalidraw's reconcile uses, so both tabs pick the same one.
 *  Equal nonces keep the server copy. `kept`: local won a tie. `taken`: the server copy replaced a local one. */
export function mergeReport(server: readonly SceneElement[], local: readonly SceneElement[]) {
  const byId = new Map(server.map((e) => [e.id, e]));
  const kept: string[] = [];
  const taken: string[] = [];
  for (const e of local) {
    const theirs = byId.get(e.id);
    if (!theirs) byId.set(e.id, e);
    else if (localWins(e, theirs)) {
      if (e.version === theirs.version) kept.push(e.id);
      byId.set(e.id, e);
    } else if (e.version !== theirs.version || nonce(e) !== nonce(theirs)) taken.push(e.id);
  }
  return { merged: [...byId.values()], kept, taken };
}

export const mergeScenes = (server: readonly SceneElement[], local: readonly SceneElement[]) =>
  mergeReport(server, local).merged;

function liveIds(elements: readonly SceneElement[]): Set<string> {
  return new Set(elements.filter((e) => !e.isDeleted).map((e) => e.id));
}

export class SceneSync {
  private readonly o: SyncOptions;
  private fetchFn: typeof fetch;
  private version = 0;
  private lastSig = "";
  private pending: readonly SceneElement[] | null = null;
  private pendingSig = "";
  private timer: ReturnType<typeof setTimeout> | null = null;
  private saving = false;
  private failures = 0;
  private disposed = false;
  private loaded = false;
  private inflight: Promise<void> | null = null;
  // The most recent scene Excalidraw reported, so a conflict merge never misses newer strokes.
  private latest: readonly SceneElement[] | null = null;
  // Ids of the live elements in the last scene the server confirmed (loaded or saved).
  private savedIds = new Set<string>();
  // id -> version of every element in the scene the server confirmed (INK-075); null until known.
  // Saves send only elements whose version differs, so a save costs the edit, not the page.
  private baseline: Map<string, number> | null = null;
  // LAN HTTP is not a secure context, so crypto.randomUUID may be missing.
  private readonly tabId = Math.random().toString(36).slice(2, 10);
  private seq = 0;
  // Set while a PUT has no definite HTTP answer (network error or timeout); the next attempt reuses it.
  private unsettled: SaveRequest | null = null;

  constructor(options: SyncOptions) {
    this.o = options;
    this.fetchFn = options.fetchFn ?? ((...a) => fetch(...a));
  }

  // A disposed instance (React StrictMode runs effects twice) must not touch the shared badge.
  private emit(state: SaveState, detail?: string) {
    if (!this.disposed) this.o.onState(state, detail);
  }

  private url() {
    return `/documents/${encodeURIComponent(this.o.documentId)}/scene`;
  }

  /** Fetch the saved scene; null (state "error") if the canvas does not exist or the API is down. */
  async load(): Promise<SceneElement[] | null> {
    this.emit("loading");
    const t0 = performance.now();
    try {
      const r = await this.fetchFn(this.url());
      this.o.clock?.mark("fetch"); // time to the response headers
      if (!r.ok) {
        this.emit("error", r.status === 404 ? "Unknown canvas" : `Load failed (${r.status})`);
        return null;
      }
      const body = (await r.json()) as { version: number; elements: SceneElement[] };
      this.o.clock?.mark("parse", { elements: body.elements.length }); // body download + parse
      this.version = body.version;
      this.lastSig = signature(body.elements);
      this.savedIds = liveIds(body.elements);
      this.baseline = versions(body.elements);
      this.pending = null;
      this.unsettled = null;
      this.loaded = true;
      record("scene.load", performance.now() - t0, { elements: body.elements.length });
      this.emit("saved");
      return body.elements;
    } catch {
      this.emit("error", "Cannot reach the Inkbridge API");
      return null;
    }
  }

  /** Call from onChange with every element including deleted ones. Cheap when nothing changed.
   *  Returns true if the elements really changed. */
  notify(elements: readonly SceneElement[]): boolean {
    if (this.disposed) return false;
    this.latest = elements;
    const sig = signature(elements);
    // Excalidraw re-fires onChange after every re-render: only a real change restarts the debounce.
    // Compare with the newest known state: while a save is pending, going back to the last saved
    // scene (an undo) is itself a change that must be saved.
    if (sig === (this.pending ? this.pendingSig : this.lastSig)) return false;
    this.pending = elements;
    this.pendingSig = sig;
    this.emit("dirty");
    this.schedule(this.o.debounceMs ?? 1500);
    return true;
  }

  /** The stored scene version the canvas matches exactly; null before load or while edits are
   *  unsaved or being saved (crop sync renders only a saved scene, decision 0015). */
  settledVersion(): number | null {
    return this.loaded && !this.disposed && !this.pending && !this.saving ? this.version : null;
  }

  /** Save now (page hidden). Resolves when the attempt finishes. */
  async flushNow() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.inflight) await this.inflight; // an in-flight save may leave newer edits pending
    await this.save(true);
  }

  /** True once the server holds every listed element (an op is acked only after its drafts are). */
  hasSaved(ids: readonly string[]): boolean {
    return ids.every((id) => this.savedIds.has(id));
  }

  /** Leave the canvas: send what is still unsaved, then stop. dispose() alone would drop the last edit. */
  async close() {
    try {
      await this.flushNow();
    } finally {
      this.dispose();
    }
  }

  dispose() {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
  }

  private schedule(ms: number) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.save();
    }, ms);
  }

  private save(flush = false): Promise<void> {
    if (this.saving || !this.pending || this.disposed) return Promise.resolve();
    this.inflight = this.doSave(flush).finally(() => (this.inflight = null));
    return this.inflight;
  }

  private buildRequest(sent: readonly SceneElement[]): SaveRequest {
    // Excalidraw mutates element objects in place, so the signature of what was sent must be taken
    // now: recomputed after the response it would include edits made during the request.
    const changed = deltaFor(this.baseline, sent);
    const body = JSON.stringify(
      changed
        ? { base_version: this.version, elements: changed, delta: true }
        : { base_version: this.version, elements: sent },
    );
    return {
      key: `${this.tabId}:${++this.seq}`,
      body,
      sent,
      sentSig: signature(sent),
      sentVersions: versions(sent),
      changed,
    };
  }

  private async doSave(flush: boolean) {
    if (!this.pending) return;
    const req = this.unsettled ?? this.buildRequest(this.pending);
    const { body, sent, sentSig, sentVersions, changed } = req;
    this.unsettled = req;
    this.saving = true;
    this.emit("saving");
    const t0 = performance.now();
    try {
      const r = await this.fetchFn(this.url(), {
        method: "PUT",
        headers: { "content-type": "application/json", "x-inkbridge-save": req.key },
        body,
        signal: AbortSignal.timeout(SAVE_TIMEOUT_MS),
        // On page hide, keepalive lets the save outlive the page; browsers cap it at 64 KiB.
        keepalive: flush && body.length < KEEPALIVE_MAX,
      });
      this.unsettled = null; // any HTTP answer is definite
      if (r.ok) {
        const saved = (await r.json()) as { version: number; timing?: Record<string, number> };
        this.version = saved.version;
        this.saving = false; // before "saved" is emitted, so settledVersion() is right in the callback
        this.lastSig = sentSig;
        this.savedIds = liveIds(sent);
        this.baseline = sentVersions;
        this.failures = 0;
        const ms = Math.round(performance.now() - t0);
        record("scene.save", ms, {
          elements: sent.length,
          sent: changed?.length ?? sent.length,
          bytes: body.length,
          ...serverParts(saved.timing),
          ...netParts(lastResource(this.url(), t0)),
        });
        if (this.pendingSig === sentSig) this.pending = null;
        if (this.pending) {
          this.emit("dirty");
          this.schedule(this.o.debounceMs ?? 1500);
        } else {
          this.emit("saved", `${ms} ms`);
        }
      } else if (r.status === 409) {
        const detail = (await r.json().catch(() => null))?.detail as
          | { last_writer?: LastWriter }
          | undefined;
        await this.resolveConflict(sent, detail?.last_writer);
      } else if (r.status >= 400 && r.status < 500) {
        // A rejected body would be rejected again, so stop retrying until the next real edit, but
        // keep the ink in memory: the next edit sends the whole scene again.
        this.emit("error", `Save rejected (${r.status}); changes are not saved yet`);
      } else {
        this.retryLater();
      }
    } catch {
      this.retryLater();
    } finally {
      this.saving = false;
    }
  }

  private retryLater() {
    const ms = RETRY_MS[Math.min(this.failures++, RETRY_MS.length - 1)];
    this.emit("retry", "Offline, retrying");
    this.schedule(ms);
  }

  // Another tab saved first. Reload the server scene, but keep the local edits in storage so a
  // conflict never silently destroys work.
  private async resolveConflict(sent: readonly SceneElement[], lastWriter?: LastWriter) {
    // Everything the user has drawn locally, including edits made while this save was in flight.
    const local = this.pending ?? sent;
    try {
      this.o.storage?.setItem(
        `inkbridge-conflict-backup-${this.o.documentId}`,
        JSON.stringify(local),
      );
    } catch {
      // storage may be unavailable (private mode); the merge below still keeps the ink
    }
    const who = lastWriter?.same_ip === false ? "device" : "tab";
    const notice = (n: number) =>
      n > 0
        ? `Another ${who} saved first; merged its changes with yours (${n} of your edits were replaced by the other ${who}, backup kept)`
        : `Another ${who} saved first; merged its changes with yours`;
    // load() replaces the baseline, so keep the one from before: it tells which edits were ours.
    const before = this.baseline;
    this.pending = null;
    this.pendingSig = "";
    this.emit("conflict", notice(0));
    const fresh = await this.load();
    // The canvas stays live during the reload: merge whatever the user has drawn since, too.
    const newest = this.latest ?? local;
    if (!fresh) {
      this.pending = newest; // could not reload: keep the ink in memory, nothing is discarded
      this.pendingSig = signature(newest);
      this.retryLater(); // the retry PUT conflicts again and so reloads again
      return;
    }
    if (this.disposed) return;
    const { merged, kept, taken } = mergeReport(fresh, newest);
    const newestVersion = new Map(newest.map((e) => [e.id, e.version]));
    const edited = taken.filter((id) => before?.get(id) !== newestVersion.get(id)).length;
    this.o.onReload(merged);
    this.emit("conflict", notice(edited));
    // A local tie win carries the same version the server holds: force it into the next delta.
    for (const id of kept) this.baseline?.set(id, -1);
    if (kept.length > 0 || signature(merged) !== this.lastSig) {
      this.pending = merged;
      this.pendingSig = signature(merged);
      this.schedule(this.o.debounceMs ?? 1500);
    }
  }
}
