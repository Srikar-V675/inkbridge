import { useSyncExternalStore, type ReactNode } from "react";
import { IconButton } from "../ui/IconButton";
import { EraserIcon, HighlighterIcon, LassoIcon, PenIcon, RedoIcon, ShapesIcon, TextIcon, UndoIcon } from "./icons";
import type { createRailStore } from "./railStore";
import { ShapeIcon } from "./props/icons";
import type { RailTool } from "./shellLogic";

export type RailStore = ReturnType<typeof createRailStore>;

const TOOLS: { tool: RailTool; label: string; icon: ReactNode }[] = [
  { tool: "pen", label: "Pen", icon: <PenIcon /> },
  { tool: "highlighter", label: "Highlighter", icon: <HighlighterIcon /> },
  { tool: "eraser", label: "Eraser", icon: <EraserIcon /> },
  { tool: "select", label: "Lasso select", icon: <LassoIcon /> },
  { tool: "shapes", label: "Shapes", icon: <ShapesIcon /> },
  { tool: "text", label: "Text", icon: <TextIcon /> },
];
const SWATCHES = [
  { label: "Ink colour charcoal", token: "--color-pen-charcoal" },
  { label: "Ink colour blue", token: "--color-pen-blue" },
  { label: "Ink colour brick", token: "--color-pen-brick" },
];

export function ToolRail({ store, toggleCard }: { store: RailStore; toggleCard: () => void }) {
  const snap = useSyncExternalStore(store.subscribe, store.get);
  return (
    <nav aria-label="Tools" className="ink-rail">
      {TOOLS.map((t) => (
        <IconButton
          key={t.tool}
          label={t.label}
          aria-pressed={snap.tool === t.tool}
          onClick={() => (snap.tool === t.tool ? toggleCard() : store.tap(t.tool))}
        >
          {t.tool === "shapes" ? <ShapeIcon shape={snap.shape} /> : t.icon}
        </IconButton>
      ))}
      <span className="ink-rail__gap" />
      {SWATCHES.map((s, i) => (
        <IconButton key={s.token} label={s.label} aria-pressed={snap.pen === i} onClick={() => store.setPen(i)}>
          <span className="ink-rail__swatch" style={{ background: `var(${s.token})` }} />
        </IconButton>
      ))}
      <span className="ink-rail__gap" />
      <IconButton label="Undo" onClick={store.undo}>
        <UndoIcon />
      </IconButton>
      <IconButton label="Redo" onClick={store.redo}>
        <RedoIcon />
      </IconButton>
    </nav>
  );
}
