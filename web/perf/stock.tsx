// Stock Excalidraw with its default UI and no shell, overlays or sync: the INK-174 baseline
// (what excalidraw.com is). Perf tooling only; built by scripts/perf/vite.perf.config.ts.
// Query: ?canvas=<id> scene to load, ?tool=hand|freedraw, ?pen=1 pen mode, ?transparent=1.
import { createRoot } from "react-dom/client";
import { useRef } from "react";
import { Excalidraw, restoreElements } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { startMeasure } from "../src/lib/measure";

const w = window as unknown as Record<string, unknown>;
w.EXCALIDRAW_THROTTLE_RENDER = new URLSearchParams(location.search).get("throttle") !== "0";
w.EXCALIDRAW_ASSET_PATH = "/excalidraw-assets/";

// The same opt-in device log as the app (?devicelog=1), so a tablet A/B compares like with like (INK-181).
startMeasure(location.search, "stock");

const q = new URLSearchParams(location.search);
export const canvas = q.get("canvas"); // exported only so the file counts as a module with exports for the lint rule
const tool = q.get("tool");

async function load() {
  if (!canvas) return [];
  const r = await fetch(`/documents/${encodeURIComponent(canvas)}/scene`);
  if (!r.ok) return [];
  return ((await r.json()) as { elements: never[] }).elements;
}

function Stock({ elements }: { elements: ReturnType<typeof restoreElements> }) {
  const api = useRef<ExcalidrawImperativeAPI | null>(null);
  const ready = useRef(false);
  const timed = () => {
    const t = performance.now();
    const ms = (w.__onChangeMs ??= []) as number[];
    ms.push(performance.now() - t); // stock's own onChange does nothing: this records the baseline of the empty callback
    if (!ready.current && api.current) {
      ready.current = true;
      if (tool) api.current.setActiveTool({ type: tool as never });
      w.__api = api.current;
      w.__ready = true;
    }
  };
  return (
    <Excalidraw
      excalidrawAPI={(a) => (api.current = a)}
      initialData={{
        elements,
        appState: {
          penMode: q.get("pen") === "1",
          ...(q.get("transparent") === "1" && { viewBackgroundColor: "transparent" }),
        },
      }}
      onChange={timed}
    />
  );
}

void load().then((els) => {
  createRoot(document.getElementById("root")!).render(<Stock elements={restoreElements(els, null)} />);
});
