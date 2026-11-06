// The shapes flyout (INK-175, docs/decisions/0075): five shape buttons beside the rail. It is a fixed-position
// sibling of the rail, never a child: the rail scrolls (INK-170) and would clip it.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { Card } from "../../ui/Card";
import { IconButton } from "../../ui/IconButton";
import type { RailStore } from "../ToolRail";
import type { ShapeTool } from "../shellLogic";
import { ShapeIcon } from "./icons";
import "./props.css";

const LABELS: [ShapeTool, string][] = [
  ["rectangle", "Rectangle"], ["diamond", "Diamond"], ["ellipse", "Ellipse"], ["arrow", "Arrow"], ["line", "Line"],
];

export function ShapesFlyout({ store, anchor, onClose }: { store: RailStore; anchor: { top: number; left: number }; onClose: () => void }) {
  const snap = useSyncExternalStore(store.subscribe, store.get);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t && (ref.current?.contains(t) || t.closest("[data-shapes-button]"))) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);
  return (
    <div ref={ref} className="ink-flyout-wrap" style={{ position: "fixed", top: anchor.top, left: anchor.left }}>
      <Card className="ink-flyout">
        <div role="toolbar" aria-label="Shapes" className="ink-flyout__row">
          {LABELS.map(([shape, label]) => (
            <IconButton
              key={shape}
              label={label}
              aria-pressed={snap.tool === "shapes" && snap.shape === shape}
              onClick={() => {
                store.pickShape(shape);
                onClose();
              }}
            >
              <ShapeIcon shape={shape} />
            </IconButton>
          ))}
        </div>
      </Card>
    </div>
  );
}
