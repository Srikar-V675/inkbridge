import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { CaptureUpdateAction, Excalidraw, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { ChunkOverlay } from "./ChunkOverlay";
import { jumpNotice, jumpPlan, resolveChunk, viewForBounds, type JumpResult } from "./chunks";
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
type Api = ExcalidrawImperativeAPI;

/** Deep link: select the chunk's live strokes and fit them, or open at the old bounds of an orphan. */
function applyJump(api: Api, jump: JumpResult) {
  const scene = api.getSceneElements();
  const plan = jumpPlan(jump, scene);
  if (!plan) return;
  if (plan.kind === "select") {
    const want = new Set(plan.ids);
    api.updateScene({
      appState: { selectedElementIds: Object.fromEntries(plan.ids.map((id) => [id, true])) as never },
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    api.scrollToContent(
      scene.filter((e) => want.has(e.id)),
      { fitToViewport: true, viewportZoomFactor: 0.7, maxZoom: 1, animate: false },
    );
    return;
  }
  const { width, height } = api.getAppState();
  const v = viewForBounds(plan.bounds, { width, height });
  api.updateScene({
    appState: { scrollX: v.scrollX, scrollY: v.scrollY, zoom: { value: v.zoom as never } },
    captureUpdate: CaptureUpdateAction.NEVER,
  });
}

function Notice({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div
      role="alert"
      style={{
        position: "absolute",
        top: 64,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 10,
        display: "flex",
        gap: 8,
        alignItems: "center",
        maxWidth: "calc(100% - 32px)",
        padding: "6px 8px 6px 12px",
        borderRadius: 6,
        font: "13px system-ui, sans-serif",
        background: "#fff3cd",
        color: "#202124",
        boxShadow: "0 1px 4px rgba(0,0,0,.15)",
      }}
    >
      <span>{text}</span>
      <button type="button" aria-label="Dismiss" onClick={onClose} style={{ border: 0, background: "none", fontSize: 16 }}>
        ×
      </button>
    </div>
  );
}

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
  const pendingJump = useRef<JumpResult | null>(null);
  const sceneReady = useRef(false);
  const [api, setApi] = useState<Api | null>(null);
  const [jump, setJump] = useState<JumpResult | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(true);

  // Load the saved scene before Excalidraw mounts so restoreElements runs ahead of initialData
  // (it keeps freedraw pressures and simulatePressure=false).
  useEffect(() => {
    const sync = new SceneSync({
      documentId: route.canvas,
      storage: window.localStorage,
      onState: (state, detail) => status.set(state, detail),
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
    // The deep-linked chunk resolves beside the scene load and never holds the canvas back: it is
    // applied on the first change event, or as soon as it arrives if the scene is already up.
    if (route.chunk) {
      void resolveChunk(route.chunk, route.canvas).then((resolved) => {
        if (cancelled) return;
        setJump(resolved);
        if (!resolved.chunk) return;
        if (sceneReady.current && apiRef.current) applyJump(apiRef.current, resolved);
        else pendingJump.current = resolved;
      });
    }
    void sync.load().then((elements) => {
      if (cancelled) return;
      if (!elements) return setInitial("failed");
      // A link wins over the remembered view (it is fitted to all ink until the chunk arrives).
      const view = route.chunk ? null : loadView(window.localStorage, route.canvas);
      const restored = restoreElements(elements as never, null);
      // Fit only a canvas that has ink: on a blank one the "first change" is the user's first stroke.
      fitOnOpen.current = !view && restored.some((e) => !e.isDeleted);
      setInitial({ elements: restored, view });
    });
    const onHide = () => {
      if (document.visibilityState === "hidden") void sync.flushNow();
    };
    const onPageHide = () => void sync.flushNow();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      sync.dispose();
    };
  }, [route.canvas, route.chunk, status]);

  const onApi = useCallback((a: Api) => {
    apiRef.current = a;
    setApi(a);
  }, []);

  const onChange = useCallback(
    (
      elements: readonly unknown[],
      appState: { scrollX: number; scrollY: number; zoom: { value: number } },
    ) => {
      syncRef.current?.notify(elements as unknown as SceneElement[]);
      // Excalidraw holds onChange back while loading, so the first call carries the loaded scene.
      sceneReady.current = true;
      if (pendingJump.current && apiRef.current) {
        const target = pendingJump.current;
        pendingJump.current = null;
        fitOnOpen.current = false;
        applyJump(apiRef.current, target);
        return;
      }
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
      {api && initial && initial !== "failed" && (
        <ChunkOverlay
          api={api}
          canvas={route.canvas}
          status={status}
          ghost={noticeOpen && jump?.outcome === "orphaned" ? jump.chunk!.bounds : null}
        />
      )}
      {noticeOpen && jump && jumpNotice(jump) && <Notice text={jumpNotice(jump)!} onClose={() => setNoticeOpen(false)} />}
      <SaveBadge store={status} />
    </div>
  );
}
