// Sends journaled elements to the server (INK-113, decision 0088). Never single-flight: a hung request
// does not hold up the next batch, only entries already in flight are skipped.
import type { Entry } from "./journal.ts";
import type { SceneElement } from "./sceneSync.ts";

export const SEND_EVERY_MS = 1000, SEND_TIMEOUT_MS = 8000, BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];

export interface SenderOptions {
  unacked: () => Entry[]; // in-memory mirror, latest per id
  send: (els: SceneElement[], signal: AbortSignal) => Promise<void>; // rejects on non-ok / network
  ack: (sent: Entry[]) => void;
  fail: (err: unknown) => void;
  now?: () => number;
}

export class Sender {
  private readonly o: SenderOptions;
  private inflight = new Set<string>(); // entry keys
  private flights = new Set<Promise<void>>();
  private failures = 0;
  private notBefore = 0;
  private interval: ReturnType<typeof setInterval> | null = null;
  constructor(o: SenderOptions) {
    this.o = o;
  }
  private now() {
    return (this.o.now ?? Date.now)();
  }
  /** Requests on the wire, and whether the last one failed (no definite answer since). */
  get busy() {
    return this.flights.size;
  }
  get failing() {
    return this.failures > 0;
  }
  tick(): void {
    const now = this.now();
    if (now < this.notBefore) return;
    const batch = this.o.unacked().filter((e) => !this.inflight.has(e.k));
    if (!batch.length) return;
    batch.forEach((e) => this.inflight.add(e.k));
    const ctl = new AbortController();
    const timeout = new Promise<never>((_, bad) => {
      ctl.signal.addEventListener("abort", () => bad(new Error("send timed out")));
    });
    const timer = setTimeout(() => ctl.abort(), SEND_TIMEOUT_MS);
    const flight: Promise<void> = Promise.race([this.o.send(batch.map((e) => e.el), ctl.signal), timeout])
      .then(
        () => {
          this.failures = 0;
          this.o.ack(batch);
        },
        (err) => {
          this.notBefore = now + BACKOFF_MS[Math.min(this.failures++, BACKOFF_MS.length - 1)];
          this.o.fail(err);
        },
      )
      .finally(() => {
        clearTimeout(timer);
        batch.forEach((e) => this.inflight.delete(e.k));
        this.flights.delete(flight);
      });
    this.flights.add(flight);
  }
  /** Send now, ignoring the backoff (online event, page hide). */
  kick() {
    this.notBefore = 0;
    this.tick();
  }
  /** Resolves when every request on the wire has settled (each ends within SEND_TIMEOUT_MS). */
  async drain() {
    await Promise.all([...this.flights]);
  }
  start(): void {
    this.interval ??= setInterval(() => this.tick(), SEND_EVERY_MS);
  }
  stop(): void {
    if (this.interval) clearInterval(this.interval);
    this.interval = null;
  }
  oldestUnackedAt(): number | null {
    let t: number | null = null;
    for (const e of this.o.unacked()) if (t === null || e.at < t) t = e.at;
    return t;
  }
}
