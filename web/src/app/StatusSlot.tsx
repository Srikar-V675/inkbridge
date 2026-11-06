// Placeholder body for the top bar status slot; INK-162 replaces it with StatusDot and the three states.
import { useSyncExternalStore } from "react";
import type { createStatusStore } from "../lib/status";
import type { SaveState } from "../sync/sceneSync";
import { CheckIcon } from "./icons";

const LABEL: Record<SaveState, string> = {
  loading: "Loading…",
  saved: "Saved",
  dirty: "Unsaved changes",
  saving: "Saving…",
  retry: "Offline, retrying",
  conflict: "Conflict",
  error: "Error",
};

export function StatusSlot({ store }: { store: ReturnType<typeof createStatusStore> }) {
  const status = useSyncExternalStore(store.subscribe, store.get);
  return (
    <span role="status" aria-live="polite" className="ink-status">
      {status.state === "saved" && <CheckIcon />}
      {LABEL[status.state]}
      {status.detail ? `: ${status.detail}` : ""}
    </span>
  );
}
