// The app shell (INK-117, docs/decisions/0066): dotted paper, top bar, tool rail and zoom control
// around the Excalidraw canvas, whose own chrome is hidden by shell.css.
import { useEffect, useMemo, type ReactNode } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { PaperDots } from "./PaperDots";
import { createRailStore } from "./railStore";
import { penColours } from "./shellLogic";
import { ToolRail } from "./ToolRail";
import { TopBar } from "./TopBar";
import { ZoomControl } from "./ZoomControl";
import "./shell.css";

export interface ShellProps {
  api: ExcalidrawImperativeAPI | null;
  title: string;
  status: ReactNode; // top bar status slot (INK-162 fills it)
  chunks?: ReactNode; // quiet "Chunks" toggle slot, left of Ask (INK-162 fills it)
  onAsk: () => void; // Ask button handler (INK-161 owns the panel it opens)
  askOpen: boolean; // aria-pressed on the Ask button
  children: ReactNode; // Excalidraw and its overlays, rendered inside the paper
}

export function Shell({ api, title, status, chunks, onAsk, askOpen, children }: ShellProps) {
  const store = useMemo(() => {
    if (!api) return null;
    const css = getComputedStyle(document.documentElement);
    return createRailStore(api as never, penColours((n) => css.getPropertyValue(n)), {
      never: CaptureUpdateAction.NEVER,
      mac: /Mac|iPhone|iPad/.test(navigator.platform),
      container: () => document.querySelector(".excalidraw"),
      makeKey: (init) => new KeyboardEvent("keydown", init),
    });
  }, [api]);
  useEffect(() => () => store?.dispose(), [store]);

  return (
    <div className="ink-shell">
      {api && <PaperDots api={api} />}
      <div className="ink-shell__canvas">{children}</div>
      <TopBar title={title} status={status} chunks={chunks} onAsk={onAsk} askOpen={askOpen} />
      {store && <ToolRail store={store} />}
      {store && <ZoomControl store={store} />}
    </div>
  );
}
