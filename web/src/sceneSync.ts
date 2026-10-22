// Framework-free load/autosave for one canvas. App.tsx wires it to Excalidraw's onChange.
// Rules (tech ref 9.1 / 10.1): never block drawing, PUT with base_version, 409 means reload.

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
  storage?: Pick<Storage, "setItem">;
  onState: (state: SaveState, detail?: string) => void;
  onReload: (elements: SceneElement[]) => void;
}

const RETRY_MS = [2000, 4000, 8000, 16000, 30000];

// Two element lists are "the same" if every element has the same id and version.
const signature = (els: readonly SceneElement[]) => els.map((e) => `${e.id}:${e.version}`).join("|");

/** Server scene plus every local element: the newer `version` wins, ties go to the server. */
export function mergeScenes(
  server: readonly SceneElement[],
  local: readonly SceneElement[],
): SceneElement[] {
  const byId = new Map(server.map((e) => [e.id, e]));
  for (const e of local) {
    const theirs = byId.get(e.id);
    if (!theirs || e.version > theirs.version) byId.set(e.id, e);
  }
  return [...byId.values()];
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
  private inflight: Promise<void> | null = null;

  constructor(options: SyncOptions) {
    this.o = options;
    this.fetchFn = options.fetchFn ?? ((...a) => fetch(...a));
  }

  private url() {
    return `/documents/${encodeURIComponent(this.o.documentId)}/scene`;
  }

  /** Fetch the saved scene; null (state "error") if the canvas does not exist or the API is down. */
  async load(): Promise<SceneElement[] | null> {
    this.o.onState("loading");
    try {
      const r = await this.fetchFn(this.url());
      if (!r.ok) {
        this.o.onState("error", r.status === 404 ? "Unknown canvas" : `Load failed (${r.status})`);
        return null;
      }
      const body = (await r.json()) as { version: number; elements: SceneElement[] };
      this.version = body.version;
      this.lastSig = signature(body.elements);
      this.pending = null;
      this.o.onState("saved");
      return body.elements;
    } catch {
      this.o.onState("error", "Cannot reach the Inkbridge API");
      return null;
    }
  }

  /** Call from onChange with every element including deleted ones. Cheap when nothing changed. */
  notify(elements: readonly SceneElement[]) {
    if (this.disposed) return;
    const sig = signature(elements);
    // Excalidraw re-fires onChange after every re-render: only a real change restarts the debounce.
    if (sig === this.lastSig || (this.pending && sig === this.pendingSig)) return;
    this.pending = elements;
    this.pendingSig = sig;
    this.o.onState("dirty");
    this.schedule(this.o.debounceMs ?? 1500);
  }

  /** Save now (page hidden). Resolves when the attempt finishes. */
  async flushNow() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.inflight) await this.inflight; // an in-flight save may leave newer edits pending
    await this.save();
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

  private save(): Promise<void> {
    if (this.saving || !this.pending || this.disposed) return Promise.resolve();
    this.inflight = this.doSave().finally(() => (this.inflight = null));
    return this.inflight;
  }

  private async doSave() {
    const sent = this.pending;
    if (!sent) return;
    this.saving = true;
    this.o.onState("saving");
    try {
      const r = await this.fetchFn(this.url(), {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ base_version: this.version, elements: sent }),
        keepalive: false,
      });
      if (r.ok) {
        this.version = ((await r.json()) as { version: number }).version;
        this.lastSig = signature(sent);
        this.failures = 0;
        if (this.pendingSig === signature(sent)) this.pending = null;
        if (this.pending) {
          this.o.onState("dirty");
          this.schedule(this.o.debounceMs ?? 1500);
        } else {
          this.o.onState("saved");
        }
      } else if (r.status === 409) {
        await this.resolveConflict(sent);
      } else if (r.status >= 400 && r.status < 500) {
        // A rejected body would be rejected again, so stop retrying until the next real edit, but
        // keep the ink in memory: the next edit sends the whole scene again.
        this.o.onState("error", `Save rejected (${r.status}); changes are not saved yet`);
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
    this.o.onState("retry", "Offline, retrying");
    this.schedule(ms);
  }

  // Another tab saved first. Reload the server scene, but keep the local edits in storage so a
  // conflict never silently destroys work.
  private async resolveConflict(sent: readonly SceneElement[]) {
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
    const notice = "Another tab saved first; merged its changes with yours";
    this.pending = null;
    this.pendingSig = "";
    this.o.onState("conflict", notice);
    const fresh = await this.load();
    if (!fresh) {
      this.pending = local; // could not reload: keep the ink in memory, nothing is discarded
      this.pendingSig = signature(local);
      return;
    }
    const merged = mergeScenes(fresh, local);
    this.o.onReload(merged);
    this.o.onState("conflict", notice);
    if (signature(merged) !== this.lastSig) {
      this.pending = merged;
      this.pendingSig = signature(merged);
      this.schedule(this.o.debounceMs ?? 1500);
    }
  }
}
