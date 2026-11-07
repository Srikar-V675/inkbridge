import { useEffect, useRef } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { isExcalidrawCanvas } from "../app/touchRouting";
import { fingerDraws } from "../app/fingerDrawsStore";
import { installFastInk, type FreedrawLike, type Surface } from "./fastInk";
import { createPenSamples, installPenSamples } from "./penSamples";
import "./fastInk.css";

// Every pen sample into the stroke, and the stroke on screen before Excalidraw draws it (INK-181,
// decision 0076). The logic lives in penSamples.ts and fastInk.ts; this only mounts the canvas.
export function FastInk({ api }: { api: ExcalidrawImperativeAPI }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const samples = createPenSamples();
    // Installed first: its capture listener must run before the fast ink's, and both before Excalidraw's.
    const offSamples = installPenSamples(window as never, globalThis as never, samples);
    let ctx: CanvasRenderingContext2D | null = null;
    let size = "";
    const surface: Surface = {
      prepare(left, top, width, height, dpr) {
        const key = `${left},${top},${width},${height},${dpr}`;
        if (key !== size) {
          size = key;
          Object.assign(canvas.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
          canvas.width = Math.round(width * dpr);
          canvas.height = Math.round(height * dpr);
          ctx = null;
        }
        // desynchronized: a low-latency canvas where the browser supports it (a hint, ignored elsewhere).
        ctx ??= canvas.getContext("2d", { desynchronized: true });
        return ctx;
      },
      clear() {
        ctx?.setTransform(1, 0, 0, 1, 0, 0);
        ctx?.clearRect(0, 0, canvas.width, canvas.height);
      },
    };
    const offInk = installFastInk({
      win: window as never,
      samples,
      state: () => {
        const s = api.getAppState();
        return {
          newElement: s.newElement as unknown as FreedrawLike | null,
          view: { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, offsetLeft: s.offsetLeft, offsetTop: s.offsetTop },
          width: s.width,
          height: s.height,
        };
      },
      mayDraw: (t) => t === "pen" || t === "mouse" || (t === "touch" && fingerDraws.get()),
      isCanvas: isExcalidrawCanvas,
      surface,
      dpr: () => window.devicePixelRatio || 1,
      frame: (cb) => void requestAnimationFrame(cb),
    });
    return () => {
      offInk();
      offSamples();
    };
  }, [api]);
  return <canvas ref={ref} className="ink-fastink" aria-hidden />;
}
