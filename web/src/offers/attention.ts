// Pen and view frames for the server's attention gate (INK-130/131). View is in scene units.
import type { AttentionView } from "../sync/opsSocket.ts";

export function toAttentionView(s: { scrollX: number; scrollY: number; zoom: { value: number }; width: number; height: number }): AttentionView | null {
  const z = s.zoom.value;
  const v = { x: -s.scrollX, y: -s.scrollY, width: s.width / z, height: s.height / z, zoom: z };
  return Object.values(v).every(Number.isFinite) ? v : null;
}

const PEN_STALE_MS = 5000; // a pen-down with no pen event for this long was a missed pen-up

/**
 * Pen changes always go out; view frames at most once per throttleMs, and the last one dropped in
 * a window is sent when it ends. `view(v, true)` bypasses the throttle (reconnect).
 */
export function createAttention(
  send: (a: { pen: boolean; view: AttentionView | null }) => void,
  now: () => number,
  throttleMs = 500,
  setTimer: (fn: () => void, ms: number) => unknown = setTimeout,
) {
  let last = -Infinity;
  let penDown = false;
  let penAt = 0;
  let pending: { view: AttentionView | null } | null = null;
  const out = (view: AttentionView | null) => {
    last = now();
    if (penDown && last - penAt > PEN_STALE_MS) penDown = false;
    send({ pen: penDown, view });
  };
  return {
    pen(down: boolean, view: AttentionView | null) {
      penDown = down;
      penAt = now();
      pending = null;
      out(view);
    },
    view(view: AttentionView | null, force = false) {
      const wait = throttleMs - (now() - last);
      if (force || wait <= 0) {
        pending = null;
        return out(view);
      }
      const armed = pending !== null;
      pending = { view };
      if (!armed)
        setTimer(() => {
          const p = pending;
          pending = null;
          if (p) out(p.view);
        }, wait);
    },
  };
}
