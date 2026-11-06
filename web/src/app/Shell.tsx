// The app shell (INK-117, docs/decisions/0066): dotted paper, top bar, tool rail and zoom control
// around the Excalidraw canvas, whose own chrome is hidden by shell.css.
import { useEffect, useState, type ReactNode } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { readRoute } from "../lib/route";
import { PaperDots } from "./PaperDots";
import { createRailStore } from "./railStore";
import { penColours } from "./shellLogic";
import { ToolRail, type RailStore } from "./ToolRail";
import { TopBar } from "./TopBar";
import { ZoomControl } from "./ZoomControl";
import "./shell.css";

export interface ShellProps {
  api: ExcalidrawImperativeAPI | null;
  title: string;
  status: ReactNode; // top bar status slot (StatusSlot, INK-162)
  chunks?: ReactNode; // quiet "Chunks" toggle slot, left of Ask (INK-162 fills it)
  overlays?: ReactNode; // chunk overlay, draft bar, notices: above rail and zoom (INK-162)
  onAsk: () => void; // Ask button handler (INK-161 owns the panel it opens)
  askOpen: boolean; // aria-pressed on the Ask button
  children: ReactNode; // Excalidraw and its overlays, rendered inside the paper
}

export function Shell({ api, title, status, chunks, overlays, onAsk, askOpen, children }: ShellProps) {
  // Built in an effect: creating it calls the API, which must not happen while React renders.
  const [store, setStore] = useState<RailStore | null>(null);
  useEffect(() => {
    if (!api) return;
    const css = getComputedStyle(document.documentElement);
    const s = createRailStore(api as never, penColours((n) => css.getPropertyValue(n)), {
      never: CaptureUpdateAction.NEVER,
      mac: /Mac|iPhone|iPad/.test(navigator.platform),
      container: () => document.querySelector(".excalidraw"),
      makeKey: (init) => new KeyboardEvent("keydown", init),
      deepLink: Boolean(readRoute().chunk),
      frame: (cb) => {
        const id = requestAnimationFrame(cb);
        return () => cancelAnimationFrame(id);
      },
    });
    setStore(s);
    return () => {
      s.dispose();
      setStore(null);
    };
  }, [api]);

  return (
    <div className="ink-shell">
      {api && <PaperDots api={api} />}
      <div className="ink-shell__canvas">{children}</div>
      <TopBar title={title} status={status} chunks={chunks} onAsk={onAsk} askOpen={askOpen} />
      {store && <ToolRail store={store} />}
      {store && <ZoomControl store={store} />}
      <div className="ink-shell__overlays">{overlays}</div>
    </div>
  );
}
