// Save status for the top bar (INK-162, decision 0068): the label and tone come from statusView.
import { useSyncExternalStore } from "react";
import { statusView, type createStatusStore } from "../lib/status";
import { StatusDot } from "../ui/StatusDot";
import { CheckIcon } from "./icons";
import "./status.css";

export function StatusSlot({ store }: { store: ReturnType<typeof createStatusStore> }) {
  const status = useSyncExternalStore(store.subscribe, store.get);
  const v = statusView(status);
  return (
    <span role="status" aria-live="polite" className={`ink-status ink-status--${v.tone}`} title={v.title}>
      {v.tone === "quiet" && <CheckIcon />}
      {v.tone === "risk" && <StatusDot tone="risk" />}
      {v.tone === "sending" && <StatusDot tone="sending" />}
      {v.label}
    </span>
  );
}
