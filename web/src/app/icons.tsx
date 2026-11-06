// Inline icons copied from the Main board (docs/tickets/v4-ref/mockups/project/Main.dc.html).
import type { ReactNode } from "react";

function Svg({ size = 22, width = 1.8, children }: { size?: number; width?: number; children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const PenIcon = () => <Svg><path d="M4 20l4-1 11-11-3-3L5 16z" /><path d="M14 6l3 3" /></Svg>;
export const HighlighterIcon = () => <Svg><path d="M9 14l7-10 4 3-7 10z" /><path d="M9 14l-4 5h5l3-2" /></Svg>;
export const EraserIcon = () => <Svg><path d="M4 15l9-9 6 6-7 7H8z" /><path d="M8 19h12" /></Svg>;
export const LassoIcon = () => <Svg><ellipse cx="12" cy="9" rx="8" ry="5" /><path d="M7 13c-2 3 0 6 3 6" /></Svg>;
export const ShapesIcon = () => <Svg><rect x="4" y="4" width="9" height="9" rx="1" /><circle cx="16.5" cy="16.5" r="4" /></Svg>;
export const TextIcon = () => <Svg><path d="M5 6h14M12 6v13" /></Svg>;
export const UndoIcon = () => <Svg><path d="M9 6L4 11l5 5" /><path d="M4 11h10a5 5 0 010 10h-2" /></Svg>;
export const RedoIcon = () => <Svg><path d="M15 6l5 5-5 5" /><path d="M20 11H10a5 5 0 000 10h-2" /></Svg>;
export const ZoomOutIcon = () => <Svg size={20}><path d="M5 12h14" /></Svg>;
export const ZoomInIcon = () => <Svg size={20}><path d="M12 5v14M5 12h14" /></Svg>;
export const BackIcon = () => <Svg><path d="M15 5l-7 7 7 7" /></Svg>;
export const AskIcon = () => <Svg size={20}><path d="M5 5h14v10H10l-5 4z" /></Svg>;
export const CheckIcon = () => <Svg size={16} width={2}><path d="M5 12l5 5 9-10" /></Svg>;
