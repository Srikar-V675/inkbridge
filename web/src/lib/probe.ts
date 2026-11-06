// Echo probe (INK-102, tech ref v4 section 12): the same small PUT from the main thread and from a
// worker. Main slow + worker fast = main-thread contention; both slow = network or browser.
import type { TimingRecord } from "./timing";

export const PROBE_BYTES = 4096;
export const PROBE_COUNT = 300;
export type ProbeRecord = TimingRecord & { t: number };

export function probeState(raw: string | null | undefined): string {
  return /^[a-z]{1,12}$/.test(raw ?? "") ? (raw as string) : "idle";
}

export async function echoSend(body: string): Promise<void> {
  const r = await fetch("/debug/echo", { method: "PUT", body, signal: AbortSignal.timeout(30_000) });
  if (!r.ok) throw new Error(`echo ${r.status}`);
}

export interface ProbeLoop {
  side: "main" | "worker";
  state: string;
  send: (body: string) => Promise<void>;
  emit: (r: ProbeRecord) => void;
  wait?: (ms: number) => Promise<void>;
  count?: number;
  now?: () => number;
}

export async function probeLoop(o: ProbeLoop): Promise<void> {
  const { side, state, send, emit, count = PROBE_COUNT } = o;
  const wait = o.wait ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = o.now ?? (() => performance.now());
  const body = "x".repeat(PROBE_BYTES);
  for (let seq = 0; seq < count; seq++) {
    const t0 = now();
    let ok = 1;
    try {
      await send(body);
    } catch {
      ok = 0;
    }
    emit({ name: `probe.${side}.${state}`, ms: Math.round(now() - t0), counts: { seq, bytes: PROBE_BYTES, ok }, t: Date.now() });
    await wait(1000);
  }
}

export async function runProbes(o: {
  state: string;
  startWorker: (onMessage: (r: ProbeRecord) => void, cfg: { state: string; count: number }) => void;
  send: (body: string) => Promise<void>;
  emit: (r: ProbeRecord) => void;
  wait?: (ms: number) => Promise<void>;
  count?: number;
}): Promise<void> {
  const state = probeState(o.state);
  const count = o.count ?? PROBE_COUNT;
  o.startWorker(o.emit, { state, count });
  await probeLoop({ side: "main", state, send: o.send, emit: o.emit, wait: o.wait, count });
}
