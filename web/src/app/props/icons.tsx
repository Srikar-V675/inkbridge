// Icons for the shapes flyout and the properties card (INK-175). Same style as ../icons.tsx.
import type { ReactNode } from "react";
import type { ShapeTool } from "../shellLogic";

function Svg({ size = 22, width = 1.8, children }: { size?: number; width?: number; children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const RectIcon = () => <Svg><rect x="4" y="6" width="16" height="12" rx="1.5" /></Svg>;
export const DiamondIcon = () => <Svg><path d="M12 3l9 9-9 9-9-9z" /></Svg>;
export const EllipseIcon = () => <Svg><ellipse cx="12" cy="12" rx="9" ry="7" /></Svg>;
export const ArrowIcon = () => <Svg><path d="M5 19L19 5" /><path d="M9 5h10v10" /></Svg>;
export const LineIcon = () => <Svg><path d="M5 19L19 5" /></Svg>;

export function ShapeIcon({ shape }: { shape: ShapeTool }) {
  switch (shape) {
    case "rectangle": return <RectIcon />;
    case "diamond": return <DiamondIcon />;
    case "ellipse": return <EllipseIcon />;
    case "arrow": return <ArrowIcon />;
    case "line": return <LineIcon />;
  }
}
