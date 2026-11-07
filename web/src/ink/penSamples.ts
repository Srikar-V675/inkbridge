// Every pen sample, not one per frame (INK-181, decision 0076). Browsers deliver pointermove at most
// once per frame and keep the stylus samples in between in getCoalescedEvents() (secure contexts
// only, so the app must be served over HTTPS). Excalidraw throttles its move handler to one call per
// frame and reads only that call's event. This collects every sample per pointer in a window
// capture listener (it runs before Excalidraw's own listener), and the patched freedraw code in
// Excalidraw (web/patches) drains it through globalThis.__inkbridgePenSamples. The fast ink layer
// reads what is not drained yet. Framework-free; the node tests drive it with plain objects.

export interface PenSample {
  clientX: number;
  clientY: number;
  pressure: number;
}

export interface SampleEvent {
  pointerId: number;
  clientX: number;
  clientY: number;
  pressure: number;
  getCoalescedEvents?: () => SampleEvent[];
}

// A stroke drained every frame never comes near this; it only bounds a pointer nobody drains.
const MAX_SAMPLES = 4096;

export function createPenSamples(max = MAX_SAMPLES) {
  const bufs = new Map<number, PenSample[]>();
  const sample = (e: SampleEvent): PenSample => ({ clientX: e.clientX, clientY: e.clientY, pressure: e.pressure });
  return {
    down(e: SampleEvent) {
      bufs.set(e.pointerId, []);
    },
    move(e: SampleEvent) {
      const buf = bufs.get(e.pointerId);
      if (!buf) return;
      let list: SampleEvent[] | undefined;
      try {
        list = e.getCoalescedEvents?.();
      } catch {
        list = undefined;
      }
      for (const c of list && list.length > 0 ? list : [e]) buf.push(sample(c));
      if (buf.length > max) buf.splice(0, buf.length - max);
    },
    /** Samples of this pointer not drained yet (the ink layer draws them ahead of Excalidraw). */
    peek(pointerId: number): readonly PenSample[] {
      return bufs.get(pointerId) ?? [];
    },
    /** Drain this pointer's samples; null when it was never seen going down (Excalidraw then uses its own event). */
    take(e: { pointerId: number }): PenSample[] | null {
      const buf = bufs.get(e.pointerId);
      if (!buf) return null;
      bufs.set(e.pointerId, []);
      return buf;
    },
  };
}

export type PenSamples = ReturnType<typeof createPenSamples>;

type Win = {
  addEventListener(t: string, cb: (e: SampleEvent) => void, o: { capture: boolean; passive: boolean }): void;
  removeEventListener(t: string, cb: (e: SampleEvent) => void, o: { capture: boolean }): void;
};

/** Listen on the window (capture, passive) and publish the hook the Excalidraw patch calls. Pointerup
 *  is not listened to: Excalidraw's pointerup handler drains the last samples after this one ran. */
export function installPenSamples(win: Win, g: { __inkbridgePenSamples?: unknown }, samples: PenSamples = createPenSamples()) {
  const down = (e: SampleEvent) => samples.down(e);
  const move = (e: SampleEvent) => samples.move(e);
  win.addEventListener("pointerdown", down, { capture: true, passive: true });
  win.addEventListener("pointermove", move, { capture: true, passive: true });
  g.__inkbridgePenSamples = (e: { pointerId: number }) => samples.take(e);
  return () => {
    win.removeEventListener("pointerdown", down, { capture: true });
    win.removeEventListener("pointermove", move, { capture: true });
    delete g.__inkbridgePenSamples;
  };
}
