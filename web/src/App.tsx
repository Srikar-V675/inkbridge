import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Excalidraw, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { readRoute } from "./route";
import { SceneSync, type SaveState, type SceneElement } from "./sceneSync";
import { createStatusStore } from "./status";
import { loadView, saveView, type View } from "./view";

const LABEL: Record<SaveState, string> = {
  loading: "Loading…",
  saved: "Saved",
  dirty: "Unsaved changes",
  saving: "Saving…",
  retry: "Offline, retrying",
  conflict: "Conflict",
  error: "Error",
};

type Restored = ReturnType<typeof restoreElements>;
type Initial = { elements: Restored; view: View | null } | "failed" | null;

function SaveBadge({ store }: { store: ReturnType<typeof createStatusStore> }) {
  const status = useSyncExternalStore(store.subscribe, store.get);
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "absolute",
        bottom: 12,
        left: "50%",
        transform: "translateX(-50%)",
        padding: "2px 10px",
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
  );
}

// Memoised so nothing outside the canvas (save status, route) can re-render it mid-stroke.
const Canvas = memo(function Canvas(props: {
  initial: { elements: Restored; view: View | null };
  onApi: (api: ExcalidrawImperativeAPI) => void;
  onChange: (elements: readonly unknown[], appState: { scrollX: number; scrollY: number; zoom: { value: number } }) => void;
}) {
  const { initial, onApi, onChange } = props;
  const initialData = useMemo(
    () => ({
      elements: initial.elements,
      ...(initial.view && {
        appState: {
          scrollX: initial.view.scrollX,
          scrollY: initial.view.scrollY,
          zoom: { value: initial.view.zoom as never },
        },
      }),
    }),
    [initial],
  );
  return <Excalidraw excalidrawAPI={onApi} initialData={initialData} onChange={onChange as never} />;
});

export default function App() {
  const route = useMemo(() => readRoute(), []);
  const status = useMemo(() => createStatusStore(), []);
  const [initial, setInitial] = useState<Initial>(null);
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const syncRef = useRef<SceneSync | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fitOnOpen = useRef(false);

  // Load the saved scene before Excalidraw mounts so restoreElements runs ahead of initialData
  // (it keeps freedraw pressures and simulatePressure=false).
  useEffect(() => {
    const sync = new SceneSync({
      documentId: route.canvas,
      storage: window.localStorage,
      onState: (state, detail) => status.set(state, detail),
      onReload: (elements) =>
        apiRef.current?.updateScene({ elements: restoreElements(elements as never, null) }),
    });
    syncRef.current = sync;
    let cancelled = false;
    void sync.load().then((elements) => {
      if (cancelled) return;
      if (!elements) return setInitial("failed");
      const view = loadView(window.localStorage, route.canvas);
      fitOnOpen.current = !view;
      setInitial({ elements: restoreElements(elements as never, null), view });
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
  }, [route.canvas, status]);

  const onApi = useCallback((api: ExcalidrawImperativeAPI) => {
    apiRef.current = api;
  }, []);

  const onChange = useCallback(
    (
      elements: readonly unknown[],
      appState: { scrollX: number; scrollY: number; zoom: { value: number } },
    ) => {
      syncRef.current?.notify(elements as unknown as SceneElement[]);
      // First open of this canvas on this device: show all the ink instead of its centre at 100%.
      // Done on the first change event that carries the loaded scene (the API handle arrives earlier).
      if (fitOnOpen.current && elements.length > 0 && apiRef.current) {
        fitOnOpen.current = false;
        apiRef.current.scrollToContent(undefined, {
          fitToViewport: true,
          viewportZoomFactor: 0.9,
          maxZoom: 1,
          animate: false,
        });
        return;
      }
      if (viewTimer.current) clearTimeout(viewTimer.current);
      viewTimer.current = setTimeout(
        () =>
          saveView(window.localStorage, route.canvas, {
            scrollX: appState.scrollX,
            scrollY: appState.scrollY,
            zoom: appState.zoom.value,
          }),
        500,
      );
    },
    [route.canvas],
  );

  return (
    <div style={{ height: "100dvh", position: "relative" }}>
      {initial && initial !== "failed" && <Canvas initial={initial} onApi={onApi} onChange={onChange} />}
      <SaveBadge store={status} />
    </div>
  );
}
