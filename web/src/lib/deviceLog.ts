// Client side of the device log (INK-102, decision 0059): names, milliseconds and counts only,
// batched to POST /debug/device-log. No DOM access at import time: the node tests import this.
import type { TimingRecord } from "./timing";

export interface DeviceRecord {
  device: string;
  name: string;
  ms: number;
  t: number;
  counts: Record<string, number>;
}
type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem?(k: string): void };

const DEVICE_KEY = "inkbridge.device";
const FLAG_KEY = "inkbridge.deviceLog";
// Math.random, not crypto.randomUUID: LAN HTTP is not a secure context.
const fresh = () => Math.random().toString(36).slice(2, 10).padEnd(8, "0");

export function deviceId(storage: Store = localStorage): string {
  try {
    const have = storage.getItem(DEVICE_KEY);
    if (have) return have;
    const id = fresh();
    storage.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    return fresh();
  }
}

/** ?devicelog=1 turns it on and remembers it, ?devicelog=0 clears it, ?probe=1 implies it. */
export function deviceLogEnabled(search: string, storage: Store = localStorage): boolean {
  const q = new URLSearchParams(search);
  try {
    if (q.get("devicelog") === "0") {
      storage.removeItem?.(FLAG_KEY);
      return false;
    }
    if (q.get("devicelog") === "1") {
      storage.setItem(FLAG_KEY, "1");
      return true;
    }
    return q.get("probe") === "1" || storage.getItem(FLAG_KEY) === "1";
  } catch {
    return q.get("probe") === "1" || q.get("devicelog") === "1";
  }
}

export function createDeviceLog(opts: { device: string; post: (body: string) => void; now?: () => number; max?: number }) {
  const { device, post, now = Date.now, max = 50 } = opts;
  let queue: DeviceRecord[] = [];
  const flush = () => {
    if (!queue.length) return;
    const body = JSON.stringify(queue);
    queue = [];
    post(body);
  };
  const add = (r: TimingRecord, t?: number) => {
    queue.push({ device, name: r.name, ms: r.ms, t: t ?? now(), counts: { ...r.counts } });
    if (queue.length >= max) flush();
  };
  return { add, flush };
}
