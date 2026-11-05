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
