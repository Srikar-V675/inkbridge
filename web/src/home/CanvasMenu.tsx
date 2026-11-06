import { useEffect, useRef, useState } from "react";
import { Button } from "../ui/Button";
import type { CanvasSummary } from "./homeLogic.ts";

export interface MenuActions {
  rename: (title: string) => void;
  pin: () => void;
  duplicate: () => void;
  archive: () => void; // restores when the canvas is archived
}

/** The actions for one canvas. Closes on Escape and on a tap outside it. */
export function CanvasMenu({ canvas, actions, onClose }: { canvas: CanvasSummary; actions: MenuActions; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(canvas.title);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [onClose]);

  const save = () => {
    const next = title.trim();
    if (!next) return; // a blank title is ignored
    if (next !== canvas.title) actions.rename(next);
    onClose();
  };
  const run = (fn: () => void) => () => {
    onClose();
    fn();
  };

  if (renaming) {
    return (
      <div ref={ref} className="ink-home-menu" role="dialog" aria-label={`Rename ${canvas.title}`}>
        <input
          className="ink-home-menu__input"
          aria-label="Canvas title"
          autoFocus
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
        />
        <Button variant="primary" onClick={save}>
          Save
        </Button>
      </div>
    );
  }
  return (
    <div ref={ref} className="ink-home-menu" role="menu" aria-label={`Actions for ${canvas.title}`}>
      <Button variant="quiet" role="menuitem" onClick={() => setRenaming(true)}>
        Rename
      </Button>
      {!canvas.archived && (
        <Button variant="quiet" role="menuitem" onClick={run(actions.pin)}>
          {canvas.pinned ? "Unpin" : "Pin"}
        </Button>
      )}
      <Button variant="quiet" role="menuitem" onClick={run(actions.duplicate)}>
        Duplicate
      </Button>
      <Button variant="quiet" role="menuitem" onClick={run(actions.archive)}>
        {canvas.archived ? "Restore" : "Archive"}
      </Button>
    </div>
  );
}
