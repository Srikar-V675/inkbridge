// Tiny external store for the save badge, so a status change re-renders only the badge and never
// the Excalidraw canvas (a canvas re-render in the middle of a stroke shows up as a hitch).
import type { SaveState } from "../sync/sceneSync";

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

export const RISK_LABEL = "Ink only in memory: do not close this tab";

export type StatusTone = "none" | "quiet" | "sending" | "notice" | "risk";
export interface StatusView {
  tone: StatusTone;
  label: string;
  title?: string;
  /** Extra line shown as visible text (a tablet has no hover). */
  detail?: string;
}

/** What the top bar says for a save state. `onDevice` is false until ink is stored on the device (later ticket). */
export function statusView(s: Status, onDevice = false): StatusView {
  const title = s.detail ? { title: s.detail } : {};
  switch (s.state) {
    case "saved":
      return { tone: "quiet", label: "Saved", ...title };
    case "loading":
      return { tone: "none", label: "Loading…" };
    case "dirty":
    case "saving":
      return { tone: "sending", label: "Saving…" };
    case "conflict": // the merge has already happened by the time a detail exists; it stays until the next save
      return { tone: "notice", label: "Merged with another device", ...(s.detail ? { detail: s.detail } : {}) };
    case "retry":
      return onDevice
        ? { tone: "sending", label: "Kept on this device, sending when the network is back" }
        : { tone: "risk", label: RISK_LABEL };
    case "error":
      return { tone: "risk", label: s.detail || RISK_LABEL };
  }
}
