import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { CaptureUpdateAction, Excalidraw, exportToBlob, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { ChunkOverlay } from "../chunks/ChunkOverlay";
import { createRefresh, wireRefresh } from "../sync/chunkRefresh";
import AskPanel from "../ask/AskPanel";
import { publishQuestion } from "../ask/ask";
import { DraftBar } from "../drafts/DraftBar";
import { createUnseen, draftBox, panTarget, planReveal, type Unseen } from "../drafts/draftView";
import { jumpNotice, jumpPlan, resolveChunk, viewForBounds, type JumpResult } from "../chunks/chunks";
import { CropSync, serverRendersCrops } from "../sync/cropSync";
import { type DraftElement } from "../drafts/drafts";
import { draftOpId, dropDrafts } from "../drafts/resolve";
import { drawOp } from "../drafts/drawOp";
import { OpsSocket } from "../sync/opsSocket";
import { readRoute } from "../lib/route";
import { createLoadClock } from "../sync/loadClock";
import { createStartupGate } from "../sync/startupGate";
import { SceneSync, type SaveState, type SceneElement } from "../sync/sceneSync";
import { createStatusStore } from "../lib/status";
import { loadView, saveView, type View } from "../lib/view";
import { initialAppState } from "../lib/excalidrawEnv";

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

/**
 * Show a freshly drawn draft (INK-076): nothing when it is in view, a pan when the pen is up and
 * no pan happened in the batch window, else a chip (the user jumps when they want). Returns the
 * time of a pan, or the previous value.
 */
function reveal(api: Api, opId: string, st: { penDown: boolean; lastPanAt: number | null }, unseen: Unseen): number | null {
  const box = draftBox(api.getSceneElements() as never, opId);
  if (!box) return st.lastPanAt;
  const s = api.getAppState();
  const view = { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, width: s.width, height: s.height };
  const now = Date.now();
  const r = planReveal({ box, view, penDown: st.penDown, lastPanAt: st.lastPanAt, now });
  if (r === "chip") unseen.add(opId);
  if (r === "pan") {
    const t = panTarget(box, view);
    // Never pass zoom: the user's zoom stays as it is.
    api.updateScene({ appState: { scrollX: t.scrollX, scrollY: t.scrollY }, captureUpdate: CaptureUpdateAction.NEVER });
    return now;
  }
  return st.lastPanAt;
}

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

// How long an op waits for its drafts to be saved before it is reported as failed (about 30 s).
const SAVE_ATTEMPTS = 15;
const SAVE_RETRY_MS = 2000;
// Op statuses whose drafts must not stay on the canvas.
const DEAD = ["failed", "expired", "rejected"];

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
  onChange: (
    elements: readonly unknown[],
    appState: { scrollX: number; scrollY: number; zoom: { value: number }; cursorButton?: string; newElement?: unknown },
  ) => void;
}) {
  const { initial, onApi, onChange } = props;
  const initialData = useMemo(
    () => ({ elements: initial.elements, appState: initialAppState(initial.view) }),
    [initial],
  );
  return <Excalidraw excalidrawAPI={onApi} initialData={initialData} onChange={onChange as never} />;
});

export default function App() {
  const route = useMemo(() => readRoute(), []);
  const status = useMemo(() => createStatusStore(), []);
  const refresh = useMemo(() => createRefresh(), []);
  useEffect(() => () => refresh.dispose(), [refresh]); // drop a pending refetch on unmount
  const [initial, setInitial] = useState<Initial>(null);
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const syncRef = useRef<SceneSync | null>(null);
  const cropRef = useRef<CropSync | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fitOnOpen = useRef(false);
  const pendingJump = useRef<JumpResult | null>(null);
  // Pen state from onChange, read when a draft arrives: a draft never pans the view mid-stroke.
  const penDown = useRef(false);
  // When the view last moved for a draft (INK-076): a second draft within the batch window waits.
  const lastPanAt = useRef<number | null>(null);
  // Drafts that were off-screen and not yet looked at (the DraftBar chip).
  const unseen = useMemo(() => createUnseen(), []);
  const sceneReady = useRef(false);
  const clock = useMemo(() => createLoadClock(), []);
  // Once per mount: switching canvases needs a page reload, so the gate never reopens.
  const gate = useMemo(() => createStartupGate(), []);
  const [api, setApi] = useState<Api | null>(null);
  const [jump, setJump] = useState<JumpResult | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(true);

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
          // CropSync skips chunks past 4096 units, so the scale here is never below 0.5 (INK-096).
          maxWidthOrHeight: 2048,
          exportPadding: 10,
        });
      },
    });
    cropRef.current = crops;
    // The server renders the crops itself when INKBRIDGE_CROP_SOURCE=server (INK-120): switch the
    // export and upload off. A failed health call leaves browser crops on.
    fetch("/health")
      .then((r) => r.json())
      .then((h) => {
        if (serverRendersCrops(h)) crops.dispose();
      })
      .catch(() => {});
    const sync = new SceneSync({
      documentId: route.canvas,
      clock,
      storage: window.localStorage,
      onState: (state, detail) => {
        status.set(state, detail);
        // Every save may have left chunks with stale crops (chunks.updated also asks, when connected).
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
      clock.mark("restore", { elements: restored.length });
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
  }, [route.canvas, route.chunk, status, clock]);

  // Resolves once Excalidraw hands over its API, so an op that arrives first waits instead of failing.
  const apiReady = useMemo(() => deferred<ExcalidrawImperativeAPI>(), []);
  const onApi = useCallback(
    (api: ExcalidrawImperativeAPI) => {
      apiRef.current = api;
      setApi(api);
      apiReady.resolve(api);
    },
    [apiReady],
  );

  // Agent ops arrive over the WebSocket once the canvas exists; they are drawn as dashed drafts.
  const canvasReady = initial !== null && initial !== "failed";
  useEffect(() => {
    if (!canvasReady) return;
    const sweep = (opId: string) => {
      const api = apiRef.current;
      if (!api) return;
      const scene = api.getSceneElementsIncludingDeleted() as never as DraftElement[];
      if (!scene.some((e) => draftOpId(e) === opId)) return; // accepted elements are never touched
      api.updateScene({ elements: dropDrafts(scene, opId) as never });
    };
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const wire = wireRefresh(refresh, document);
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
        const api = apiRef.current ?? (await apiReady.promise);
        const ids = await drawOp(api, op, persist);
        lastPanAt.current = reveal(api, op.op_id, { penDown: penDown.current, lastPanAt: lastPanAt.current }, unseen);
        return ids;
      },
      // A save left chunks with stale crops: export them once the canvas is idle (INK-057).
      onChunksUpdated: () => {
        cropRef.current?.request();
        wire.onChunksUpdated();
      },
      // A push lost while the socket was down is gone, so the chunk list refetches on every connect.
      onConnection: (c) => {
        wire.onConnection(c);
        if (c) publishQuestion(null); // pushes sent while the socket was down are lost
      },
      onQuestionUpdate: publishQuestion,
      // An op that failed, expired or was rejected elsewhere must not leave drafts behind.
      onOpUpdated: (m) => {
        if (DEAD.includes(m.status)) sweep(m.op_id);
      },
      onOpError: (m) => {
        // The op ended while it was being drawn (op.updated came before the drafts existed), so
        // the ack was refused: the drafts just drawn have no live op and must go too.
        if (m.code === "invalid_transition" && DEAD.includes(String(m.detail))) sweep(m.op_id);
        else console.warn("op refused by the server", m);
      },
    });
    const cancel = gate.whenReady(() => socket.start());
    // A missing first change event must never leave the socket off.
    const fallback = window.setTimeout(() => gate.open(), 3000);
    return () => {
      window.clearTimeout(fallback);
      cancel();
      socket.dispose();
      wire.off();
    };
  }, [canvasReady, route.canvas, apiReady, refresh, unseen, gate]);

  const onChange = useCallback(
    (
      elements: readonly unknown[],
      appState: { scrollX: number; scrollY: number; zoom: { value: number }; cursorButton?: string; newElement?: unknown },
    ) => {
      // Set before any early return below, so every change event keeps it current.
      penDown.current = appState.cursorButton === "down" || appState.newElement != null;
      if (syncRef.current?.notify(elements as unknown as SceneElement[])) cropRef.current?.activity();
      // The first change event means the canvas holds the loaded scene, so crops can be exported;
      // a reopened tab then catches up on crops left stale while it was closed.
      // Excalidraw holds onChange back while loading, so the first call carries the loaded scene.
      if (!sceneReady.current) {
        clock.mark("firstChange");
        clock.total();
        // Crop sync and the ops socket wait until the scene has painted and the browser is idle.
        gate.whenReady(() => cropRef.current?.start());
        gate.open();
      }
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
    [route.canvas, clock, gate],
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
          refresh={refresh}
        />
      )}
      {noticeOpen && jump && jumpNotice(jump) && <Notice text={jumpNotice(jump)!} onClose={() => setNoticeOpen(false)} />}
      {api && <DraftBar api={api} sync={syncRef} documentId={route.canvas} unseen={unseen} />}
      {api && initial && initial !== "failed" && <AskPanel api={api} canvas={route.canvas} />}
      <SaveBadge store={status} />
    </div>
  );
}
