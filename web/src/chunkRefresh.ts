// One shared "refresh the chunk list" signal (INK-079). Saves, chunk pushes, socket reconnects and
// the tablet waking up all fire it; a burst becomes one listener call after the delay, so the
// overlay fetches at most once per burst and never on every stroke.

export interface Refresh {
  fire(): void;
  subscribe(l: () => void): () => void;
}

/** Burst of fire() calls -> one listener call after `delayMs`. */
export function createRefresh(
  delayMs = 800,
  setTimer: (fn: () => void, ms: number) => unknown = setTimeout,
): Refresh {
  const listeners = new Set<() => void>();
  let pending = false;
  return {
    fire() {
      if (pending) return;
      pending = true;
      setTimer(() => {
        pending = false;
        listeners.forEach((l) => l());
      }, delayMs);
    },
    subscribe(l) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}

/** Calls fn when the document becomes visible (a tablet waking up). Returns unsubscribe. */
export function onVisible(
  doc: {
    visibilityState: string;
    addEventListener(t: string, f: () => void): void;
    removeEventListener(t: string, f: () => void): void;
  },
  fn: () => void,
): () => void {
  const handler = () => {
    if (doc.visibilityState === "visible") fn();
  };
  doc.addEventListener("visibilitychange", handler);
  return () => doc.removeEventListener("visibilitychange", handler);
}
