import { record } from "./timing.ts";

export type Mark = "fetch" | "parse" | "restore" | "firstChange";

/** One clock per canvas open: each mark records the time since the previous mark (not cumulative),
 *  and total() records the time from the start to now (first change event = scene painted). */
export function createLoadClock(now: () => number = () => performance.now(), rec = record) {
  const t0 = now();
  let last = t0;
  return {
    mark(name: Mark, counts: Record<string, number> = {}) {
      const t = now();
      rec(`load.${name}`, t - last, counts);
      last = t;
    },
    total(counts: Record<string, number> = {}) {
      rec("load.total", now() - t0, counts);
    },
  };
}
export type LoadClock = ReturnType<typeof createLoadClock>;
