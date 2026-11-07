import { useEffect, useSyncExternalStore } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { Button } from "../ui/Button";
import { fingerDraws } from "./fingerDrawsStore";
import { installTouchInput, whenLoaded } from "./touchInput";
import { isExcalidrawCanvas, penPatch, viewPatch } from "./touchRouting";

// One finger pans, two pinch, the pen draws (INK-173, docs/decisions/0072). The router lives in
// touchInput.ts; this file only wires it to Excalidraw and the top bar.
const frame = (cb: () => void) => {
  const id = requestAnimationFrame(cb);
  return () => cancelAnimationFrame(id);
};

export function TouchRouting({ api }: { api: ExcalidrawImperativeAPI }) {
  const on = useSyncExternalStore(fingerDraws.subscribe, fingerDraws.get);
  useEffect(
    () =>
      installTouchInput({
        win: window as never,
        isCanvas: isExcalidrawCanvas,
        tool: () => api.getAppState().activeTool.type,
        view: () => {
          const s = api.getAppState();
          return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, offsetLeft: s.offsetLeft, offsetTop: s.offsetTop };
        },
        setView: (v) =>
          api.updateScene({
            appState: viewPatch(v, api.getAppState().zoom.value) as never,
            captureUpdate: CaptureUpdateAction.NEVER,
          }),
        elements: () => api.getSceneElements() as never,
        fingerDraws: fingerDraws.get,
        clearSelection: () => api.updateScene({ appState: { selectedElementIds: {} }, captureUpdate: CaptureUpdateAction.NEVER }),
        hidden: () => document.hidden,
        now: () => performance.now(),
        schedule: frame,
      }),
    [api],
  );
  // The stored setting is applied after load; the initial penMode: true stays the default.
  useEffect(
    () => whenLoaded(api, frame, () => api.updateScene({ appState: penPatch(on) as never, captureUpdate: CaptureUpdateAction.NEVER })),
    [api, on],
  );
  return null;
}

export function FingerToggle() {
  const on = useSyncExternalStore(fingerDraws.subscribe, fingerDraws.get);
  return (
    <Button variant="quiet" className="ink-chunk-toggle" aria-pressed={on} onClick={() => fingerDraws.set(!on)} title="Let a finger draw (for no stylus)">
      Finger draws
    </Button>
  );
}
