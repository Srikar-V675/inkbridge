// Pen and view frames for the server's attention gate (INK-130/131). View is in scene units.
import type { AttentionView } from "../sync/opsSocket.ts";

export function toAttentionView(s: { scrollX: number; scrollY: number; zoom: { value: number }; width: number; height: number }): AttentionView | null {
  const z = s.zoom.value;
  const v = { x: -s.scrollX, y: -s.scrollY, width: s.width / z, height: s.height / z, zoom: z };
  return Object.values(v).every(Number.isFinite) ? v : null;
}

/** Pen changes always go out; view frames at most once per throttleMs (a dropped one is carried by the next). */
export function createAttention(send: (a: { pen: boolean; view: AttentionView | null }) => void, now: () => number, throttleMs = 500) {
  let last = -Infinity;
  let penDown = false;
  return {
    pen(down: boolean, view: AttentionView | null) {
      last = now();
      penDown = down;
      send({ pen: down, view });
    },
    view(view: AttentionView | null) {
      const t = now();
      if (t - last < throttleMs) return;
      last = t;
      send({ pen: penDown, view });
    },
  };
}
