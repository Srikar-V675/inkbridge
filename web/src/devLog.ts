// Dev only: only ever imported dynamically under import.meta.env.DEV (main.tsx), so the production
// build contains neither this module nor the /__log endpoint name.
import type { TimingRecord } from "./timing";

let queue: string[] = [];
let timer: number | undefined;

function flush() {
  timer = undefined;
  const body = queue.join("\n");
  queue = [];
  void fetch("/__log", { method: "POST", body }).catch(() => {}); // fire and forget, off the drawing path
}

export function devSink(r: TimingRecord) {
  const line =
    `timing ${r.name} ms=${r.ms}` +
    Object.entries(r.counts)
      .map(([k, v]) => ` ${k}=${v}`)
      .join("");
  if (r.ms > 1000) console.warn(line);
  else console.debug(line);
  queue.push(line);
  timer ??= window.setTimeout(flush, 2000); // batch: one request per 2 s at most
}
