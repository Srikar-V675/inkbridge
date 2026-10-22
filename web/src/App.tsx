import { useEffect, useMemo, useRef, useState } from "react";
import { Excalidraw, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { readRoute } from "./route";
import { SceneSync, type SaveState, type SceneElement } from "./sceneSync";

const LABEL: Record<SaveState, string> = {
  loading: "Loading…",
  saved: "Saved",
  dirty: "Unsaved changes",
  saving: "Saving…",
  retry: "Offline, retrying",
  conflict: "Conflict",
  error: "Error",
};

type Initial = { elements: ReturnType<typeof restoreElements> } | "failed" | null;

export default function App() {
  const route = useMemo(() => readRoute(), []);
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const [initial, setInitial] = useState<Initial>(null);
  const [status, setStatus] = useState<{ state: SaveState; detail?: string }>({ state: "loading" });
  const syncRef = useRef<SceneSync | null>(null);

  // Load the saved scene before Excalidraw mounts so restoreElements runs ahead of initialData
  // (it keeps freedraw pressures and simulatePressure=false).
  useEffect(() => {
    const sync = new SceneSync({
      documentId: route.canvas,
      storage: window.localStorage,
      onState: (state, detail) =>
        setStatus((s) => (s.state === state && s.detail === detail ? s : { state, detail })),
      onReload: (elements) => {
        apiRef.current?.updateScene({ elements: restoreElements(elements as never, null) });
      },
    });
    syncRef.current = sync;
    let cancelled = false;
    void sync.load().then((elements) => {
      if (cancelled) return;
      setInitial(elements ? { elements: restoreElements(elements as never, null) } : "failed");
    });
    const onHide = () => {
      if (document.visibilityState === "hidden") void sync.flushNow();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onHide);
      sync.dispose();
    };
  }, [route.canvas]);

  return (
    <div style={{ height: "100vh", position: "relative" }}>
      {initial && initial !== "failed" && (
        <Excalidraw
          excalidrawAPI={(a) => {
            apiRef.current = a;
          }}
          initialData={{ elements: initial.elements, scrollToContent: true }}
          onChange={(elements) => syncRef.current?.notify(elements as unknown as SceneElement[])}
        />
      )}
      <div
        role="status"
        aria-live="polite"
        style={{
          position: "absolute",
          top: 8,
          right: 8,
          padding: "2px 8px",
          borderRadius: 4,
          font: "12px system-ui, sans-serif",
          background: status.state === "saved" ? "#e6f4ea" : "#fff3cd",
          color: "#202124",
          pointerEvents: "none",
          zIndex: 10,
        }}
      >
        {LABEL[status.state]}
        {status.detail ? `: ${status.detail}` : ""}
      </div>
    </div>
  );
}
