// Main-thread stall measures for the device log (INK-102): a heartbeat gap and frame-time buckets.

/** tick() every ~100 ms; a gap over `limit` ms means the main thread was blocked. */
export function createHeartbeat(now: () => number, onGap: (ms: number) => void, limit = 200) {
  let last = now();
  return {
    tick() {
      const t = now();
      if (t - last > limit) onGap(t - last);
      last = t;
    },
    reset() {
      last = now();
    },
  };
}

export function bucketCounts(deltas: number[]) {
  const c = { le20: 0, le34: 0, le50: 0, le100: 0, gt100: 0, frames: deltas.length };
  for (const d of deltas) {
    if (d <= 20) c.le20++;
    else if (d <= 34) c.le34++;
    else if (d <= 50) c.le50++;
    else if (d <= 100) c.le100++;
    else c.gt100++;
  }
  return c;
}

export type FrameKind = "pointer" | "wheel";

/** Counts frame-to-frame deltas between start() and stop(); one loop at a time. */
export function createFrameMeter(opts: { raf: (cb: (t: number) => void) => void; onDone: (kind: FrameKind, deltas: number[]) => void }) {
  let running: FrameKind | null = null;
  let run = 0; // a callback left over from an earlier run must not feed the next one
  let deltas: number[] = [];
  return {
    start(kind: FrameKind) {
      if (running) return;
      running = kind;
      deltas = [];
      const mine = ++run;
      let prev: number | undefined;
      const loop = (t: number) => {
        if (run !== mine || !running) return;
        if (prev !== undefined) deltas.push(t - prev);
        prev = t;
        opts.raf(loop);
      };
      opts.raf(loop);
    },
    stop() {
      if (!running) return;
      const kind = running;
      running = null;
      opts.onDone(kind, deltas);
    },
  };
}
