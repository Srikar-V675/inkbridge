// The app shell (INK-117, docs/decisions/0066): dotted paper, top bar, tool rail and zoom control
// around the Excalidraw canvas, whose own chrome is hidden by shell.css.
import { useEffect, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { readRoute } from "../lib/route";
import { PaperDots } from "./PaperDots";
import { PropsCard } from "./props/PropsCard";
import { loadFont, measure } from "./props/measureText";
import { createPropsStore } from "./props/propsStore";
import { createRailStore } from "./railStore";
import { penColours } from "./shellLogic";
import { ToolRail, type RailStore } from "./ToolRail";
import { TopBar } from "./TopBar";
import { uiScale } from "./uiScaleStore";
import { ZoomControl } from "./ZoomControl";
import "./shell.css";
import "./uiScale.css";

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
  const scale = useSyncExternalStore(uiScale.subscribe, uiScale.get); // UI size, INK-177
  // Built in an effect: creating it calls the API, which must not happen while React renders.
  const [stores, setStores] = useState<{ rail: RailStore; props: ReturnType<typeof createPropsStore> } | null>(null);
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
    const p = createPropsStore(api as never, {
      never: CaptureUpdateAction.NEVER,
      immediately: CaptureUpdateAction.IMMEDIATELY,
      mac: /Mac|iPhone|iPad/.test(navigator.platform),
      container: () => document.querySelector(".excalidraw"),
      makeKey: (init) => new KeyboardEvent("keydown", init),
      nonce: () => Math.floor(Math.random() * 2 ** 31),
      now: () => Date.now(),
      measure,
      loadFont,
      freedrawKind: () => (s.get().tool === "highlighter" ? "highlighter" : "pen"),
    });
    setStores({ rail: s, props: p });
    return () => {
      s.dispose();
      p.dispose();
      setStores(null);
    };
  }, [api]);

  return (
    <div className="ink-shell" style={{ "--ui-scale": scale } as CSSProperties}>
      {api && <PaperDots api={api} />}
      <div className="ink-shell__canvas">{children}</div>
      <TopBar title={title} status={status} chunks={chunks} onAsk={onAsk} askOpen={askOpen} />
      {stores && <ToolRail store={stores.rail} toggleCard={stores.props.toggleCard} />}
      {stores && <ZoomControl store={stores.rail} />}
      <div className="ink-shell__overlays">{overlays}</div>
      {/* After the overlays at the same layer, so the card sits above chunk chips (INK-175, 0075). */}
      {stores && <PropsCard store={stores.props} rail={stores.rail} />}
    </div>
  );
}
