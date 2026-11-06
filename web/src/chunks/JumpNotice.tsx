import { Toast } from "../ui/Toast";
import "./ChunkOverlay.css";

/** The "source changed" notice after a deep link. `onClose` is the user's Dismiss; `onExpire` is the timeout. */
export function JumpNotice({ text, onClose, onExpire }: { text: string; onClose: () => void; onExpire: () => void }) {
  return (
    <div className="ink-notice-dock">
      <Toast message={text} actionLabel="Dismiss" onAction={onClose} onDismiss={onExpire} durationMs={20000} />
    </div>
  );
}
