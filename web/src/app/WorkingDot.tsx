// The working dot (INK-198, decision 0113): beside the save status while the agent works on this canvas.
import { useSyncExternalStore } from "react";
import type { createActivityStore } from "./activity";
import "./WorkingDot.css";

export function WorkingDot({ store }: { store: ReturnType<typeof createActivityStore> }) {
  const v = useSyncExternalStore(store.subscribe, store.get);
  if (!v.visible) return null;
  return (
    <span className="ink-working" role="img" aria-label={v.label} title={v.label}>
      <span className="ink-working__dot" />
    </span>
  );
}
