// Icons for the shapes picker and the properties card (INK-175). Same style as ../icons.tsx.
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

// Properties card icons.
export const ChevronUpIcon = () => <Svg size={20}><path d="M6 15l6-6 6 6" /></Svg>;
export const ChevronDownIcon = () => <Svg size={20}><path d="M6 9l6 6 6-6" /></Svg>;

export const FillHachureIcon = () => <Svg size={20}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 20L20 8M4 16L16 4M12 20l8-8M4 8l4-4" /></Svg>;
export const FillCrossIcon = () => <Svg size={20}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 20L20 8M4 16L16 4M16 20L4 8M20 16L8 4" /></Svg>;
export const FillSolidIcon = () => <Svg size={20}><rect x="4" y="4" width="16" height="16" rx="2" fill="currentColor" /></Svg>;

export const WidthIcon = ({ w }: { w: number }) => <Svg size={20} width={w}><path d="M4 12h16" /></Svg>;

export const StyleSolidIcon = () => <Svg size={20}><path d="M4 12h16" /></Svg>;
export const StyleDashedIcon = () => <Svg size={20}><path d="M3 12h4M10 12h4M17 12h4" /></Svg>;
export const StyleDottedIcon = () => <Svg size={20}><path d="M4 12h.01M9 12h.01M14 12h.01M19 12h.01" strokeWidth="3" /></Svg>;

export const SloppyIcon = ({ level }: { level: number }) => (
  <Svg size={20}>
    {level === 0 && <path d="M3 12h18" />}
    {level === 1 && <path d="M3 12c3-2 5 2 9 0s6 1 9-1" />}
    {level === 2 && <path d="M3 13c2-5 4 5 6-1s4 4 6-2 4 3 6-1" />}
  </Svg>
);

export const EdgeSharpIcon = () => <Svg size={20}><path d="M5 19V5h14" /></Svg>;
export const EdgeRoundIcon = () => <Svg size={20}><path d="M5 19V12a7 7 0 017-7h7" /></Svg>;

/** Arrow end: the shaft runs to the right, `flip` mirrors it for the start of the arrow. */
export function HeadIcon({ head, flip }: { head: string; flip?: boolean }) {
  return (
    <Svg size={20}>
      <g transform={flip ? "translate(24 0) scale(-1 1)" : undefined}>
        <path d="M3 12h12" />
        {head === "arrow" && <path d="M14 7l6 5-6 5" />}
        {head === "triangle" && <path d="M14 7l7 5-7 5z" />}
        {head === "bar" && <path d="M18 6v12" />}
        {head === "dot" && <circle cx="18" cy="12" r="3" />}
        {head === "none" && <path d="M15 12h2" />}
      </g>
    </Svg>
  );
}

export const ArrowSharpIcon = () => <Svg size={20}><path d="M4 18L12 6l8 12" /></Svg>;
export const ArrowRoundIcon = () => <Svg size={20}><path d="M4 18c0-8 6-12 16-12" /></Svg>;
export const ArrowElbowIcon = () => <Svg size={20}><path d="M4 18h8V6h8" /></Svg>;

export const AlignLeftIcon = () => <Svg size={20}><path d="M4 6h16M4 12h10M4 18h13" /></Svg>;
export const AlignCenterIcon = () => <Svg size={20}><path d="M4 6h16M7 12h10M5.5 18h13" /></Svg>;
export const AlignRightIcon = () => <Svg size={20}><path d="M4 6h16M10 12h10M7 18h13" /></Svg>;

export const ToBackIcon = () => <Svg size={20}><rect x="9" y="9" width="11" height="11" rx="1" /><path d="M5 15V5h10" /></Svg>;
export const BackwardIcon = () => <Svg size={20}><path d="M12 5v12M7 12l5 5 5-5" /></Svg>;
export const ForwardIcon = () => <Svg size={20}><path d="M12 19V7M7 12l5-5 5 5" /></Svg>;
export const ToFrontIcon = () => <Svg size={20}><rect x="4" y="4" width="11" height="11" rx="1" /><path d="M9 20h11V9" /></Svg>;
export const DuplicateIcon = () => <Svg size={20}><rect x="8" y="8" width="12" height="12" rx="1.5" /><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3" /></Svg>;
export const TrashIcon = () => <Svg size={20}><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13" /></Svg>;
export const LockIcon = () => <Svg size={20}><rect x="5" y="11" width="14" height="9" rx="1.5" /><path d="M8 11V8a4 4 0 018 0v3" /></Svg>;
