// Inline icons for the canvases home, drawn like the ones in app/icons.tsx.
import type { ReactNode } from "react";

function Svg({ size = 20, children }: { size?: number; children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const SearchIcon = () => <Svg><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></Svg>;
export const PlusIcon = () => <Svg><path d="M12 5v14M5 12h14" /></Svg>;
export const MoreIcon = () => <Svg size={22}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></Svg>;
export const PinIcon = () => <Svg size={14}><path d="M9 4h6l-1 6 3 3H7l3-3z" /><path d="M12 13v7" /></Svg>;
