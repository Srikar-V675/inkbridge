import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Excalidraw, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { rejectOp, type DraftElement } from "./drafts";
import { drawOp } from "./drawOp";
import { OpsSocket } from "./opsSocket";
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

// How long an op waits for its drafts to be saved before it is reported as failed (about 30 s).
const SAVE_ATTEMPTS = 15;
const SAVE_RETRY_MS = 2000;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
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
  }, [route.canvas, status]);

  // Resolves once Excalidraw hands over its API, so an op that arrives first waits instead of failing.
  const apiReady = useMemo(() => deferred<ExcalidrawImperativeAPI>(), []);
  const onApi = useCallback(
    (api: ExcalidrawImperativeAPI) => {
      apiRef.current = api;
      apiReady.resolve(api);
    },
    [apiReady],
  );

  // Agent ops arrive over the WebSocket once the canvas exists; they are drawn as dashed drafts.
  const canvasReady = initial !== null && initial !== "failed";
  useEffect(() => {
    if (!canvasReady) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new OpsSocket({
      url: `${scheme}://${window.location.host}/ws?document=${encodeURIComponent(route.canvas)}`,
      onOp: async (op) => {
        // Saving now also makes the server's next placement see the newest ink. flushNow does not
        // throw when a save fails (offline, 409 merge, 4xx), so check that the server really holds
        // the drafts: an acked op is never replayed, so an unsaved draft lost to a reload would be
        // gone for good. Give up after a while; op.failed then sweeps the drafts.
        const persist = async (elements: readonly unknown[]) => {
          const sync = syncRef.current;
          if (!sync) throw new Error("the canvas is not loaded");
          const scene = elements as SceneElement[];
          const ids = scene
            .filter((e) => e.id.startsWith(op.payload.id_prefix) && !e.isDeleted)
            .map((e) => e.id);
          sync.notify(scene);
          for (let attempt = 0; ; attempt++) {
            await sync.flushNow();
            if (sync.hasSaved(ids)) return;
            if (attempt >= SAVE_ATTEMPTS) throw new Error("the drafts could not be saved");
            await new Promise((r) => setTimeout(r, SAVE_RETRY_MS));
          }
        };
        return drawOp(apiRef.current ?? (await apiReady.promise), op, persist);
      },
      onOpUpdated: (m) => {
        // An op that failed, expired or was rejected elsewhere must not leave drafts behind.
        const api = apiRef.current;
        if (!api || !["failed", "expired", "rejected"].includes(m.status)) return;
        const prefix = `${m.op_id}:`;
        const scene = api.getSceneElementsIncludingDeleted() as never as DraftElement[];
        if (!scene.some((e) => e.id.startsWith(prefix) && !e.isDeleted)) return;
        api.updateScene({ elements: rejectOp(scene, prefix) as never });
      },
      onOpError: (m) => console.warn("op refused by the server", m),
    });
    socket.start();
    return () => socket.dispose();
  }, [canvasReady, route.canvas, apiReady]);

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
