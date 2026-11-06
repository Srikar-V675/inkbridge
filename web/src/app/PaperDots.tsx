import { useEffect, useRef } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { paperLayer } from "./shellLogic";

/**
 * The dotted paper behind the transparent canvas (INK-174, decision 0073). The dots live on a layer one
 * tile larger than the view, moved by `transform` only while panning (compositor, no repaint); the
 * tile-size variable is written only when the zoom changes. No React state, no re-render on pan.
 */
export function PaperDots({ api }: { api: ExcalidrawImperativeAPI }) {
  const layer = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = layer.current;
    if (!node) return;
    let lastSize: number | null = null;
    let raf = 0;
    const paint = () => {
      raf = 0;
      const s = api.getAppState();
      const d = paperLayer({ scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value }, lastSize);
      if (d.size !== null) {
        lastSize = d.size;
        node.style.setProperty("--ink-dot-size", `${d.size}px`); // zoom only: this one repaints
      }
      // Whole device pixels: a fractional offset would make the compositor resample (soften) the dots.
      const dpr = window.devicePixelRatio || 1;
      const snap = (n: number) => Math.round(n * dpr) / dpr;
      node.style.transform = `translate3d(${snap(d.x)}px, ${snap(d.y)}px, 0)`; // pan: compositor only
    };
    // One write per frame, queued after Excalidraw's own throttled redraw (it requests its frame
    // earlier in the same commit), so the dots and the ink move in the same frame.
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    paint();
    schedule(); // the initialData scroll can land after the API handle
    const off = api.onScrollChange(schedule);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [api]);
  return (
    <div className="ink-paper" aria-hidden>
      <div className="ink-paper__dots" ref={layer} />
    </div>
  );
}
