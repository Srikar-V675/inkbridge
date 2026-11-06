// The chunk overlay's on/off state, shared by the top bar toggle and the overlay (INK-162).
export interface ChunkViewState {
  on: boolean;
  session: number;
}

export function createChunkView() {
  let current: ChunkViewState = { on: false, session: 0 };
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    /** Turning on starts a new session: the overlay never shows a list fetched before. */
    toggle() {
      current = current.on ? { on: false, session: current.session } : { on: true, session: current.session + 1 };
      listeners.forEach((l) => l());
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}
export type ChunkView = ReturnType<typeof createChunkView>;
