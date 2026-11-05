// Timing records for the browser (INK-067). Names, milliseconds and counts only: never scene
// content. No import.meta.env here: the node tests import this module.
export interface TimingRecord {
  name: string;
  ms: number;
  counts: Record<string, number>;
}
export type TimingSink = (r: TimingRecord) => void;

let sink: TimingSink = () => {};
export function setTimingSink(s: TimingSink) {
  sink = s;
}

/** Add a sink beside the current one (the device log and the dev sink both listen). */
export function addTimingSink(s: TimingSink) {
  const prev = sink;
  sink = (r) => {
    try {
      prev(r);
    } catch {
      /* a failing sink must not hide the next one */
    }
    try {
      s(r);
    } catch {
      /* never break the caller */
    }
  };
}

/** Server save timing (ms) as `s_*` counts; anything that is not a number is dropped. */
export function serverParts(timing: Record<string, unknown> | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(timing ?? {})) if (typeof v === "number") out[`s_${k}`] = v;
  return out;
}

/** Browser view of one request: n_conn > 0 means a new TCP connection; n_wait is upload plus server time. */
export function netParts(e: PerformanceResourceTiming | undefined): Record<string, number> {
  if (!e) return {};
  const d = (x: number) => Math.max(0, Math.round(x));
  return {
    n_pre: d(e.requestStart - e.startTime),
    n_conn: d(e.connectEnd - e.connectStart),
    n_wait: d(e.responseStart - e.requestStart),
    n_recv: d(e.responseEnd - e.responseStart),
  };
}

export function lastResource(url: string, since: number): PerformanceResourceTiming | undefined {
  if (typeof performance === "undefined" || typeof location === "undefined") return undefined;
  const abs = new URL(url, location.href).href;
  const hit = performance.getEntriesByName(abs, "resource").filter((e) => e.startTime >= since - 1).at(-1);
  performance.clearResourceTimings(); // the default buffer holds 250 entries and then silently stops
  return hit as PerformanceResourceTiming | undefined;
}

/** Hand one measurement to the sink; a failing sink never breaks the caller. */
export function record(name: string, ms: number, counts: Record<string, number> = {}) {
  try {
    sink({ name, ms: Math.round(ms), counts });
  } catch {
    /* never break the caller */
  }
}

export async function timed<T>(
  name: string,
  fn: () => Promise<T> | T,
  counts: (result: T | undefined) => Record<string, number> = () => ({}),
): Promise<T> {
  const t0 = performance.now();
  let result: T | undefined;
  try {
    result = await fn();
    return result;
  } finally {
    let c: Record<string, number> = {};
    try {
      c = counts(result);
    } catch {
      /* counts are best effort */
    }
    record(name, performance.now() - t0, c);
  }
}
