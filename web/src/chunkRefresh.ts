// One shared "refresh the chunk list" signal (INK-079). Saves, chunk pushes, socket reconnects and
// the tablet waking up all fire it; a burst becomes one listener call after the delay, so the
// overlay fetches at most once per burst and never on every stroke.

export interface Refresh {
  fire(): void;
  subscribe(l: () => void): () => void;
  /** Clears a pending burst (unmount). Listeners stay, so the signal still works afterwards. */
  dispose(): void;
}

/** Burst of fire() calls -> one listener call after `delayMs`. */
export function createRefresh(
  delayMs = 800,
  setTimer: (fn: () => void, ms: number) => unknown = setTimeout,
  clearTimer: (handle: any) => void = clearTimeout,
): Refresh {
  const listeners = new Set<() => void>();
  let pending = false;
  let handle: unknown = undefined;
  return {
    fire() {
      if (pending) return;
      pending = true;
      handle = setTimer(() => {
        pending = false;
        listeners.forEach((l) => l());
      }, delayMs);
    },
    subscribe(l) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    dispose() {
      if (pending) clearTimer(handle);
      pending = false;
    },
  };
}

export interface VisibleDoc {
  visibilityState: string;
  addEventListener(t: string, f: () => void): void;
  removeEventListener(t: string, f: () => void): void;
}

/** Calls fn when the document becomes visible (a tablet waking up). Returns unsubscribe. */
export function onVisible(doc: VisibleDoc, fn: () => void): () => void {
  const handler = () => {
    if (doc.visibilityState === "visible") fn();
  };
  doc.addEventListener("visibilitychange", handler);
  return () => doc.removeEventListener("visibilitychange", handler);
}

/**
 * The three events that mean the chunk list may be stale: a chunk push, a socket connect (a push
 * lost while the socket was down is gone), and the document becoming visible. `off` removes the
 * visibility listener. Pure, so the wiring is tested without React.
 */
export function wireRefresh(refresh: Refresh, doc: VisibleDoc) {
  return {
    onChunksUpdated: () => refresh.fire(),
    onConnection: (connected: boolean) => {
      if (connected) refresh.fire();
    },
    off: onVisible(doc, () => refresh.fire()),
  };
}
