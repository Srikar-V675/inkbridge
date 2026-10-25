import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Excalidraw, exportToBlob, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { CropSync } from "./cropSync";
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
  const cropRef = useRef<CropSync | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fitOnOpen = useRef(false);

  // Load the saved scene before Excalidraw mounts so restoreElements runs ahead of initialData
  // (it keeps freedraw pressures and simulatePressure=false).
  useEffect(() => {
    // Server-made chunks get their crop PNGs from here, only while the canvas is idle and saved.
    const crops = new CropSync({
      documentId: route.canvas,
      settledVersion: () => sync.settledVersion(),
      exportPng: async (ids) => {
        const api = apiRef.current;
        if (!api) return null;
        const want = new Set(ids);
        const elements = api.getSceneElements().filter((e) => want.has(e.id));
        if (elements.length === 0) return null;
        return exportToBlob({
          elements,
          appState: { exportBackground: true, viewBackgroundColor: "#ffffff" },
          files: api.getFiles(),
          mimeType: "image/png",
          maxWidthOrHeight: 2048,
          exportPadding: 10,
        });
      },
    });
    cropRef.current = crops;
    const sync = new SceneSync({
      documentId: route.canvas,
      storage: window.localStorage,
      onState: (state, detail) => {
        status.set(state, detail);
        // Every save may have left chunks with stale crops (until INK-042 pushes chunks.updated).
        if (state === "saved") crops.request();
      },
      onReload: (elements) => {
        const api = apiRef.current;
        if (!api) return;
        // Keep the live objects of local elements (one may be a stroke still being drawn) and
        // restore only the ones that came from the server.
        const live = new Set<unknown>(api.getSceneElementsIncludingDeleted());
        const restored = restoreElements(elements.filter((e) => !live.has(e)) as never, null);
        const byId = new Map(restored.map((e) => [e.id, e]));
        api.updateScene({
          elements: elements.map((e) => (live.has(e) ? e : byId.get(e.id))).filter(Boolean) as never,
        });
      },
    });
    syncRef.current = sync;
    let cancelled = false;
    void sync.load().then((elements) => {
      if (cancelled) return;
      if (!elements) return setInitial("failed");
      const view = loadView(window.localStorage, route.canvas);
      const restored = restoreElements(elements as never, null);
      // Fit only a canvas that has ink: on a blank one the "first change" is the user's first stroke.
      fitOnOpen.current = !view && restored.some((e) => !e.isDeleted);
      setInitial({ elements: restored, view });
    });
    const onHide = () => {
      if (document.visibilityState !== "hidden") return;
      onBlur();
      void sync.flushNow();
    };
    const onPageHide = () => void sync.flushNow();
    // A pen, finger or mouse held down on the canvas means drawing: no crop export until it lifts.
    const down = new Set<number>();
    const onDown = (e: PointerEvent) => (down.add(e.pointerId), crops.setDrawing(true));
    const onUp = (e: PointerEvent) => {
      down.delete(e.pointerId);
      crops.setDrawing(down.size > 0);
    };
    // A pointerup that never arrives (window lost focus mid-stroke) must not stall crop sync.
    const onBlur = () => (down.clear(), crops.setDrawing(false));
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointerup", onUp, true);
    window.addEventListener("pointercancel", onUp, true);
    window.addEventListener("blur", onBlur);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("pointercancel", onUp, true);
      window.removeEventListener("blur", onBlur);
      sync.dispose();
      crops.dispose();
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
      if (syncRef.current?.notify(elements as unknown as SceneElement[])) cropRef.current?.activity();
      // The first change event means the canvas holds the loaded scene, so crops can be exported;
      // a reopened tab then catches up on crops left stale while it was closed.
      cropRef.current?.start();
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
