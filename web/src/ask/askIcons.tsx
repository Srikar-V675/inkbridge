// Inline icons copied from the Ask and Thread boards (docs/tickets/v4-ref/mockups/project/). Local so ask/ does not import app/.
import type { ReactNode } from "react";

function Svg({ size = 20, width = 1.8, children }: { size?: number; width?: number; children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const CloseIcon = () => <Svg size={20}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
export const SendIcon = () => <Svg width={2}><path d="M12 19V5M6 11l6-6 6 6" /></Svg>;
export const ScopeIcon = () => <Svg size={18}><path d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3" /></Svg>;
export const BackIcon = () => <Svg size={18}><path d="M15 5l-7 7 7 7" /></Svg>;
