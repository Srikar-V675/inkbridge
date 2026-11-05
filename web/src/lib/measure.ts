// Opt-in device measurement (INK-102, decision 0059): ?devicelog=1 or ?probe=1. Off = no timers,
// no frame loop, no beacons. Names, milliseconds and counts only.
import { createDeviceLog, deviceId, deviceLogEnabled } from "./deviceLog";
import { echoSend, probeState, runProbes } from "./probe";
import { bucketCounts, createFrameMeter, createHeartbeat } from "./stalls";
import { addTimingSink } from "./timing";

const URL_PATH = "/debug/device-log";

export function startMeasure(search: string = location.search): void {
  if (!deviceLogEnabled(search)) return;
  const log = createDeviceLog({
    device: deviceId(),
    post: (body) => {
      // The server answers 404 when INKBRIDGE_DEVICE_LOG is off; that is ignored on purpose.
      if (!navigator.sendBeacon?.(URL_PATH, body)) {
        fetch(URL_PATH, { method: "POST", body, keepalive: true }).catch(() => {});
      }
    },
  });
  addTimingSink((r) => log.add(r));
  setInterval(log.flush, 5000);
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && log.flush());
  addEventListener("pagehide", log.flush);

  const beat = createHeartbeat(() => performance.now(), (ms) => log.add({ name: "main.gap", ms: Math.round(ms), counts: {} }));
  setInterval(beat.tick, 100);
  document.addEventListener("visibilitychange", beat.reset); // a hidden tab throttles timers to 1 s

  const frames = createFrameMeter({
    raf: (cb) => void requestAnimationFrame(cb),
    onDone: (kind, deltas) =>
      log.add({ name: `frames.${kind}`, ms: Math.round(deltas.reduce((a, b) => a + b, 0)), counts: bucketCounts(deltas) }),
  });
  const opts = { capture: true, passive: true } as const;
  addEventListener("pointerdown", () => frames.start("pointer"), opts);
  addEventListener("pointerup", () => frames.stop(), opts);
  addEventListener("pointercancel", () => frames.stop(), opts);
  let wheelEnd: ReturnType<typeof setTimeout> | undefined;
  addEventListener(
    "wheel",
    () => {
      frames.start("wheel");
      clearTimeout(wheelEnd);
      wheelEnd = setTimeout(frames.stop, 300);
    },
    opts,
  );

  const q = new URLSearchParams(search);
  if (q.get("probe") === "1") {
    performance.setResourceTimingBufferSize(1000);
    void runProbes({
      state: probeState(q.get("state")),
      send: echoSend,
      emit: (r) => log.add(r, r.t), // straight to the log: probe records skip the timing sink
      startWorker: (onMessage, cfg) => {
        const w = new Worker(new URL("./probeWorker.ts", import.meta.url), { type: "module" });
        w.onmessage = (e) => onMessage(e.data);
        w.postMessage(cfg);
      },
    });
  }
}
