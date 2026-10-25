// Chunk boxes and ids drawn as plain DOM over the canvas. UI state only: nothing here touches the
// Excalidraw scene, so the overlay can never be autosaved (docs/decisions/0013).
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { listChunks, toScreen, type Bounds, type Chunk, type View } from "./chunks";

type StatusStore = { get: () => { state: string }; subscribe: (l: () => void) => () => void };

function currentView(api: ExcalidrawImperativeAPI): View {
  const s = api.getAppState();
  return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value };
}

/** Follows the canvas scroll and zoom without re-rendering the canvas itself. */
function useView(api: ExcalidrawImperativeAPI): View {
  const [view, setView] = useState<View>(() => currentView(api));
  useEffect(
    () => api.onScrollChange((scrollX, scrollY, zoom) => setView({ scrollX, scrollY, zoom: zoom.value })),
    [api],
  );
  return view;
}

/** Active chunks while `on`, refetched after every save (the server re-derives chunks on save). */
function useChunks(canvas: string, on: boolean, status: StatusStore): Chunk[] {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  useEffect(() => {
    if (!on) return;
    let alive = true;
    const load = () => void listChunks(canvas).then((rows) => alive && setChunks(rows));
    load();
    let last = status.get().state;
    const unsubscribe = status.subscribe(() => {
      const now = status.get().state;
      if (now === "saved" && last !== "saved") load();
      last = now;
    });
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [canvas, on, status]);
  return on ? chunks : [];
}

const box = (b: Bounds, v: View): React.CSSProperties => {
  const s = toScreen(b, v);
  return { position: "absolute", left: s.left, top: s.top, width: s.width, height: s.height, boxSizing: "border-box" };
};

const label: React.CSSProperties = {
  position: "absolute",
  top: -16,
  left: -1,
  padding: "0 4px",
  font: "11px ui-monospace, monospace",
  lineHeight: "16px",
  whiteSpace: "nowrap",
  background: "#1971c2",
  color: "#fff",
  borderRadius: "3px 3px 0 0",
};

export function ChunkOverlay(props: {
  api: ExcalidrawImperativeAPI;
  canvas: string;
  status: StatusStore;
  /** Old bounds of an orphaned deep-linked chunk, shown until the notice is dismissed. */
  ghost: Bounds | null;
}) {
  const { api, canvas, status, ghost } = props;
  const [on, setOn] = useState(false);
  const view = useView(api);
  const chunks = useChunks(canvas, on, status);

  return (
    <>
      {(on || ghost) && (
        <div
          data-testid="chunk-overlay"
          aria-hidden
          style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 4 }}
        >
          {on &&
            chunks.map((c) => (
              <div key={c.id} data-chunk-id={c.id} style={{ ...box(c.bounds, view), border: "1.5px solid #1971c2" }}>
                <span style={label}>{c.id}</span>
              </div>
            ))}
          {ghost && (
            <div data-testid="chunk-ghost" style={{ ...box(ghost, view), border: "2px dashed #e8590c" }} />
          )}
        </div>
      )}
      <button
        type="button"
        aria-pressed={on}
        onClick={() => setOn((v) => !v)}
        style={{
          position: "absolute",
          right: 12,
          bottom: 60,
          zIndex: 10,
          padding: "4px 10px",
          borderRadius: 6,
          border: "1px solid #ced4da",
          font: "12px system-ui, sans-serif",
          background: on ? "#1971c2" : "#fff",
          color: on ? "#fff" : "#202124",
        }}
      >
        {on ? "Hide chunks" : "Show chunks"}
        {on && chunks.length > 0 ? ` (${chunks.length})` : ""}
      </button>
    </>
  );
}
