// Tiny external store for the save badge, so a status change re-renders only the badge and never
// the Excalidraw canvas (a canvas re-render in the middle of a stroke shows up as a hitch).
import type { SaveState } from "./sceneSync";

export interface Status {
  state: SaveState;
  detail?: string;
}

export function createStatusStore() {
  let current: Status = { state: "loading" };
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    set(state: SaveState, detail?: string) {
      if (current.state === state && current.detail === detail) return;
      current = { state, detail };
      listeners.forEach((l) => l());
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}
