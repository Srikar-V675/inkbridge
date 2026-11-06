// Framework-free crop sync for server-made chunks (tech ref 9.4, docs/decisions/0015).
// The server flags a chunk png_stale when its ink changes; only the browser can render Excalidraw,
// so this exports the chunk's elements and uploads the PNG. Rules: never while drawing (pointer
// down or a change in the last ~2 s), only when the canvas equals a saved scene version, and the
// upload carries that version so the server can refuse a crop of older ink.

import { record } from "../lib/timing.ts";

export interface StaleChunk {
  id: string;
  element_ids: string[];
  status: string;
  png_stale: boolean;
  bounds?: { width: number; height: number };
}

// INK-096: the same limit as server/src/inkbridge/imaging.py (a test on each side pins it). The
// export is capped at 2048 px, so 4096 units keeps the scale >= 0.5; the element cap bounds how
// long one export blocks the main thread. A chunk past either is never exported or read.
export const MAX_READ_UNITS = 4096;
export const MAX_CROP_ELEMENTS = 1500;

/** Why this chunk gets no crop, or null when it can be exported (recomputed every pass). */
export function cropSkipReason(c: StaleChunk): string | null {
  const side = c.bounds ? Math.max(c.bounds.width, c.bounds.height) : 0;
  if (side > MAX_READ_UNITS || c.element_ids.length > MAX_CROP_ELEMENTS) {
    return `too large to read (${Math.round(side)} units, ${c.element_ids.length} elements)`;
  }
  return null;
}

/** True when GET /health says the server renders crops (INKBRIDGE_CROP_SOURCE=server, INK-120). */
export function serverRendersCrops(health: unknown): boolean {
  return (
    typeof health === "object" &&
    health !== null &&
    (health as { crop_source?: unknown }).crop_source === "server"
  );
}

const BACKOFF_FIRST_MS = 30_000;
const BACKOFF_MAX_MS = 600_000;

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
  /** Gap between two chunk exports, so input is handled between them (default 250 ms). */
  slotMs?: number;
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
  private readonly slotMs: number;
  private readonly skipped = new Set<string>(); // too-large chunks already recorded
  private readonly failures = new Map<string, { n: number; at: number }>();
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
    this.slotMs = options.slotMs ?? 250;
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

  /** A chunk that failed is not retried for 30 s, doubling to 10 min; success clears it. */
  private fail(id: string) {
    const n = (this.failures.get(id)?.n ?? 0) + 1;
    const delay = Math.min(BACKOFF_FIRST_MS * 2 ** (n - 1), BACKOFF_MAX_MS);
    this.failures.set(id, { n, at: this.now() + delay });
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
    const t0 = performance.now();
    let listed = 0;
    try {
      const r = await this.fetchFn(staleUrl(this.o.documentId));
      if (!r.ok) return; // the next request or poll retries
      const chunks = ((await r.json()) as StaleChunk[]).filter(
        (c) => c.png_stale && c.status === "active",
      );
      listed = chunks.length;
      const listedIds = new Set(chunks.map((c) => c.id));
      for (const id of [...this.failures.keys()]) if (!listedIds.has(id)) this.failures.delete(id);
      const exportable = chunks.filter((c) => {
        if (!cropSkipReason(c)) return true;
        if (!this.skipped.has(c.id)) {
          this.skipped.add(c.id);
          record("crop.skipped", 0, { elements: c.element_ids.length });
        }
        return false;
      });
      const ready = () => exportable.filter((c) => this.now() >= (this.failures.get(c.id)?.at ?? 0));
      for (const c of ready()) {
        await this.yieldFn(); // a pen-down queued during the last upload is handled first
        if (this.busy(since, version)) return void (this.wanted = !this.disposed);
        let png: Blob | null;
        const e0 = performance.now();
        try {
          png = await this.o.exportPng(c.element_ids);
        } catch {
          png = null; // one chunk that cannot be rendered must not starve the chunks after it
        }
        record("crop.export", performance.now() - e0, { elements: c.element_ids.length });
        // An edit during the export may be in the picture but not in the saved scene: drop it.
        if (this.busy(since, version)) return void (this.wanted = !this.disposed);
        if (!png) {
          this.fail(c.id);
          continue;
        }
        const form = new FormData();
        form.append("image", png, `${c.id}.png`);
        form.append("scene_version", String(version));
        const u0 = performance.now();
        const put = await this.fetchFn(`/regions/${encodeURIComponent(c.id)}/image`, {
          method: "PUT",
          body: form,
        });
        record("crop.upload", performance.now() - u0, { bytes: png.size });
        // 409: the stored scene moved on (another tab saved); wait for this tab's next save.
        if (put.status === 409) return void (this.refusedAt = version);
        if (put.ok) this.failures.delete(c.id);
        else this.fail(c.id);
        // One chunk per idle slot: the rest follows after slotMs, if the canvas is still idle.
        this.wanted = ready().some((o) => o.id !== c.id);
        return;
      }
    } catch {
      // API unreachable: the crops stay stale and the next request or poll catches up.
    } finally {
      if (listed) record("crop.pass", performance.now() - t0, { chunks: listed });
      this.running = false;
      if (this.wanted) this.schedule(Math.max(this.idleLeft(), this.slotMs));
    }
  }
}
