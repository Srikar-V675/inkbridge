import { Toast } from "../ui/Toast";
import "./ChunkOverlay.css";

/** The "source changed" notice after a deep link (was an inline-styled banner in App.tsx). */
export function JumpNotice({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className="ink-notice-dock">
      <Toast message={text} actionLabel="Dismiss" onAction={onClose} onDismiss={onClose} durationMs={20000} />
    </div>
  );
}
