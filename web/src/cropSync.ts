// Framework-free crop sync for server-made chunks (tech ref 9.4, docs/decisions/0015).
// The server flags a chunk png_stale when its ink changes; only the browser can render Excalidraw,
// so this exports the chunk's elements and uploads the PNG. Rules: never while drawing (pointer
// down or a change in the last ~2 s), only when the canvas equals a saved scene version, and the
// upload carries that version so the server can refuse a crop of older ink.

export interface StaleChunk {
  id: string;
  element_ids: string[];
  status: string;
  png_stale: boolean;
}

export interface CropSyncOptions {
  documentId: string;
  /** Render these elements of the live canvas to a PNG; null if none of them is drawn. */
  exportPng: (elementIds: readonly string[]) => Promise<Blob | null>;
  /** The scene version the canvas matches exactly, or null while edits are unsaved. */
  settledVersion: () => number | null;
  fetchFn?: typeof fetch;
  idleMs?: number;
  now?: () => number;
  /** Lets the browser handle input between exports (each export blocks the main thread). */
  yieldFn?: () => Promise<void>;
}

// INK-033 adds GET /documents/{id}/chunks?png_stale=1; until then the regions list serves it.
const staleUrl = (doc: string) =>
  `/documents/${encodeURIComponent(doc)}/regions?chunks=true&png_stale=true&status=active&limit=500`;

export class CropSync {
  private readonly o: CropSyncOptions;
  private readonly fetchFn: typeof fetch;
  private readonly idleMs: number;
  private readonly now: () => number;
  private readonly yieldFn: () => Promise<void>;
  private lastActivity = -Infinity;
  private drawing = false;
  private wanted = false;
  private running = false;
  private disposed = false;
  private started = false;
  // Scene version that got a 409: this tab is behind the stored scene, so polling again at the
  // same version would only export and be refused again. Cleared by the next save or reload.
  private refusedAt: number | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(options: CropSyncOptions) {
    this.o = options;
    this.fetchFn = options.fetchFn ?? ((...a) => fetch(...a));
    this.idleMs = options.idleMs ?? 2000;
    this.now = options.now ?? (() => Date.now());
    this.yieldFn = options.yieldFn ?? (() => new Promise((r) => setTimeout(r, 0)));
  }

  /** Call once the canvas shows the loaded scene: catch up (a reopened tab) after the idle delay,
   *  then poll; the WebSocket's chunks.updated can call request(). Nothing runs before this. */
  start(pollMs = 30_000) {
    if (this.started) return;
    this.started = true;
    this.activity();
    const poll = () => {
      if (this.disposed) return;
      this.request();
      this.pollTimer = setTimeout(poll, pollMs);
    };
    poll();
  }

  /** Something may have gone stale (load, a save, chunks.updated): sync once the canvas is idle. */
  request() {
    this.wanted = true;
    if (this.started) this.schedule(this.idleLeft());
  }

  /** A scene change or pointer event: restarts the idle clock. */
  activity() {
    this.lastActivity = this.now();
  }

  /** Pointer down / up on the canvas. Nothing is exported while it is down. */
  setDrawing(down: boolean) {
    this.drawing = down;
    this.activity();
  }

  dispose() {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }

  private idleLeft() {
    return this.drawing ? this.idleMs : Math.max(0, this.lastActivity + this.idleMs - this.now());
  }

  private busy(since: number, version: number) {
    return (
      this.disposed ||
      this.drawing ||
      this.lastActivity !== since ||
      this.o.settledVersion() !== version
    );
  }

  private schedule(ms: number) {
    if (this.timer || this.disposed) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, ms);
  }

  private async run() {
    if (this.disposed || this.running || !this.wanted) return;
    const wait = this.idleLeft();
    if (wait > 0) return this.schedule(wait);
    const version = this.o.settledVersion();
    // Unsaved edits or a save in flight: the canvas is not any stored scene yet. Check again after
    // the idle delay (no request is made), so a "saved" state emitted mid-save (a conflict reload)
    // is not lost until the next poll.
    if (version === null) return this.schedule(this.idleMs);
    if (version === this.refusedAt) return;
    this.running = true;
    this.wanted = false;
    const since = this.lastActivity;
    try {
      const r = await this.fetchFn(staleUrl(this.o.documentId));
      if (!r.ok) return; // the next request or poll retries
      const chunks = ((await r.json()) as StaleChunk[]).filter(
        (c) => c.png_stale && c.status === "active",
      );
      for (const c of chunks) {
        await this.yieldFn(); // a pen-down queued during the last upload is handled first
        if (this.busy(since, version)) return void (this.wanted = !this.disposed);
        let png: Blob | null;
        try {
          png = await this.o.exportPng(c.element_ids);
        } catch {
          png = null; // one chunk that cannot be rendered must not starve the chunks after it
        }
        // An edit during the export may be in the picture but not in the saved scene: drop it.
        if (this.busy(since, version)) return void (this.wanted = !this.disposed);
        if (!png) continue;
        const form = new FormData();
        form.append("image", png, `${c.id}.png`);
        form.append("scene_version", String(version));
        const put = await this.fetchFn(`/regions/${encodeURIComponent(c.id)}/image`, {
          method: "PUT",
          body: form,
        });
        // 409: the stored scene moved on (another tab saved); wait for this tab's next save.
        if (put.status === 409) return void (this.refusedAt = version);
      }
    } catch {
      // API unreachable: the crops stay stale and the next request or poll catches up.
    } finally {
      this.running = false;
      if (this.wanted) this.schedule(this.idleLeft());
    }
  }
}
