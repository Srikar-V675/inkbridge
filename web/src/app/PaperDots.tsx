import { useEffect, useRef } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { paperDots } from "./shellLogic";

/** The dotted paper behind the transparent canvas. Writes CSS variables straight on the element: no React state, no re-render on pan. */
export function PaperDots({ api }: { api: ExcalidrawImperativeAPI }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const paint = () => {
      const s = api.getAppState();
      const d = paperDots({ scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value });
      node.style.setProperty("--ink-dot-size", `${d.size}px`);
      node.style.setProperty("--ink-dot-x", `${d.x}px`);
      node.style.setProperty("--ink-dot-y", `${d.y}px`);
    };
    paint();
    const raf = requestAnimationFrame(paint); // the initialData scroll can land after the API handle
    const off = api.onScrollChange(paint);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [api]);
  return <div className="ink-paper" ref={el} aria-hidden />;
}
