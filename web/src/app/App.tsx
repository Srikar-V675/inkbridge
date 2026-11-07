import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CaptureUpdateAction, Excalidraw, exportToBlob, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { ChunkOverlay, ChunkToggle } from "../chunks/ChunkOverlay";
import { FingerToggle, TouchRouting } from "./TouchLayer";
import { FastInk } from "../ink/FastInk";
import { createChunkView } from "../chunks/chunkView";
import { JumpNotice } from "../chunks/JumpNotice";
import { createRefresh, onVisible, wireRefresh } from "../sync/chunkRefresh";
import AskPanel from "../ask/AskPanel";
import { publishDelta, publishQuestion } from "../ask/ask";
import { DraftBar } from "../drafts/DraftBar";
import { createDraftStore, reconcile, reloadWithDrafts } from "../drafts/draftStore";
import { createUnseen, draftBox, panTarget, planReveal, type Unseen } from "../drafts/draftView";
import { jumpNotice, jumpPlan, resolveChunk, viewForBounds, type JumpResult } from "../chunks/chunks";
import { CropSync, serverRendersCrops } from "../sync/cropSync";
import { type DraftElement } from "../drafts/drafts";
import { fetchDrafts } from "../drafts/resolve";
import { measureOp } from "../drafts/drawOp";
import { OpsSocket } from "../sync/opsSocket";
import { FocusToggle, OfferLayer } from "../offers/OfferLayer";
import { createOfferStore } from "../offers/offerStore";
import { createAttention, toAttentionView } from "../offers/attention";
import { listOffers } from "../offers/offers";
import { LiveDelta } from "../sync/liveDelta";
import type { Location } from "../lib/route";
import { createLoadClock } from "../sync/loadClock";
import { createStartupGate } from "../sync/startupGate";
import { openJournal } from "../sync/journal";
import { SceneSync, type SceneElement } from "../sync/sceneSync";
import { titleHint } from "../lib/nav";
import { createStatusStore } from "../lib/status";
import { loadView, saveView, type View } from "../lib/view";
import { initialAppState } from "../lib/excalidrawEnv";
import { fetchTitle } from "./canvasTitle";
import { CanvasState } from "./CanvasState";
import { Shell } from "./Shell";
import { StatusSlot } from "./StatusSlot";

type Restored = ReturnType<typeof restoreElements>;
type Initial = { elements: Restored; view: View | null } | "failed" | "missing" | null;
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

// Module level so the reference is stable and the memo below never re-renders Excalidraw for it.
// Excalidraw 0.18 cannot hide its toolbar through UIOptions; shell.css hides the chrome (decision 0066).
const UI_OPTIONS = {
  canvasActions: {
    changeViewBackgroundColor: false,
    clearCanvas: false,
    export: false,
    loadScene: false,
    saveToActiveFile: false,
    toggleTheme: false,
    saveAsImage: false,
  },
  tools: { image: false },
} as const;

// What Excalidraw starts with; null when the canvas did not open (it is unmounted then).
type InitialData = { elements: Restored; appState: ReturnType<typeof initialAppState> } | null;

// Memoised so nothing outside the canvas (save status, route) can re-render it mid-stroke.
// It takes a promise: Excalidraw starts initialising now, while the scene is still downloading.
const Canvas = memo(function Canvas(props: {
  initialData: Promise<InitialData>;
  onApi: (api: ExcalidrawImperativeAPI) => void;
  onChange: (
    elements: readonly unknown[],
    appState: { scrollX: number; scrollY: number; zoom: { value: number }; cursorButton?: string; newElement?: unknown },
  ) => void;
}) {
  const { initialData, onApi, onChange } = props;
  return <Excalidraw excalidrawAPI={onApi} initialData={initialData as never} onChange={onChange as never} UIOptions={UI_OPTIONS} />;
});

export default function App({ route }: { route: Extract<Location, { kind: "canvas" }> }) {
  const status = useMemo(() => createStatusStore(), []);
  const refresh = useMemo(() => createRefresh(), []);
  const chunkView = useMemo(() => createChunkView(), []);
  useEffect(() => () => refresh.dispose(), [refresh]); // drop a pending refetch on unmount
  const [initial, setInitial] = useState<Initial>(null);
  const sceneData = useMemo(() => deferred<InitialData>(), []);
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const syncRef = useRef<SceneSync | null>(null);
  const cropRef = useRef<CropSync | null>(null);
  const liveRef = useRef<LiveDelta | null>(null);
  // Merges what the server has beyond the device copy; runs once the scene is mounted (INK-113).
  const catchUpRef = useRef<(() => void) | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fitOnOpen = useRef(false);
  const pendingJump = useRef<JumpResult | null>(null);
  // Pen state from onChange, read when a draft arrives: a draft never pans the view mid-stroke.
  const penDown = useRef(false);
  // When the view last moved for a draft (INK-076): a second draft within the batch window waits.
  const lastPanAt = useRef<number | null>(null);
  // Drafts that were off-screen and not yet looked at (the DraftBar chip).
  const unseen = useMemo(() => createUnseen(), []);
  // The placed drafts the server holds; the scene shows exactly these (INK-115).
  const drafts = useMemo(() => createDraftStore(), []);
  const offerStore = useMemo(() => createOfferStore(), []);
  const sceneReady = useRef(false);
  const clock = useMemo(() => createLoadClock(), []);
  // Once per canvas view: a switch remounts this component, so the gate is per canvas.
  const gate = useMemo(() => createStartupGate(), []);
  const [api, setApi] = useState<Api | null>(null);
  const [jump, setJump] = useState<JumpResult | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(true);
  // The toast times out, but the ghost box stays until the user dismisses (INK-162 review).
  const [ghostOpen, setGhostOpen] = useState(true);
  const expireNotice = useCallback(() => setNoticeOpen(false), []);
  const closeNotice = useCallback(() => (setNoticeOpen(false), setGhostOpen(false)), []);
  const [askOpen, setAskOpen] = useState(false);
  const [askThread, setAskThread] = useState<string | null>(null);
  const closeAsk = () => {
    setAskOpen(false);
    setAskThread(null);
  };
  // The home passes the canvas title along: no id flash, and no request before the first paint.
  const hint = useMemo(() => titleHint(route.canvas), [route.canvas]);
  const [title, setTitle] = useState(hint ?? route.canvas);
  useEffect(() => {
    // A hint can be stale (renamed elsewhere), so it is refreshed once the canvas has painted.
    // fetchTitle answers the raw id when the request fails: that must not replace a real title.
    if (hint) return gate.whenReady(() => void fetchTitle(route.canvas).then((t) => t !== route.canvas && setTitle(t)));
    void fetchTitle(route.canvas).then(setTitle);
  }, [route.canvas, hint, gate]);

  // Load the saved scene before Excalidraw mounts so restoreElements runs ahead of initialData
  // (it keeps freedraw pressures and simulatePressure=false).
  useEffect(() => {
    // Server-made chunks get their crop PNGs from here, only while the canvas is idle and saved.
    let sync: SceneSync | null = null; // created once the journal is open; Excalidraw does not wait for it
    const crops = new CropSync({
      documentId: route.canvas,
      settledVersion: () => sync?.settledVersion() ?? null,
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
    void openJournal().then((journal) => {
      if (cancelled) return;
      const created = new SceneSync({
        documentId: route.canvas,
        clock,
        journal,
        onState: (state, detail) => {
          status.setDevice(created.journalOk);
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
          try {
            api.updateScene({
              elements: reloadWithDrafts(
                elements.map((e) => (live.has(e) ? e : byId.get(e.id))).filter(Boolean) as DraftElement[],
                api.getSceneElementsIncludingDeleted() as never as DraftElement[],
                drafts.list(),
              ) as never,
              // Ink another device wrote is not this user's edit: Ctrl+Z must not undo it.
              captureUpdate: CaptureUpdateAction.NEVER,
            });
          } catch {} // the final save on leave (sync.close) can land after Excalidraw unmounted
        },
      });
      sync = created;
      syncRef.current = created;
      created.load().then((elements) => {
        if (cancelled) return;
        if (!elements) {
          sceneData.resolve(null);
          return setInitial(created.notFound ? "missing" : "failed");
        }
        status.setDevice(created.journalOk);
        created.sender.start();
        // A link wins over the remembered view (it is fitted to all ink until the chunk arrives).
        const view = route.chunk ? null : loadView(window.localStorage, route.canvas);
        const restored = restoreElements(elements as never, null);
        clock.mark("restore", { elements: restored.length });
        // Fit only a canvas that has ink: on a blank one the "first change" is the user's first stroke.
        fitOnOpen.current = !view && restored.some((e) => !e.isDeleted);
        sceneData.resolve({ elements: restored, appState: initialAppState(view) });
        setInitial({ elements: restored, view });
      });
    });
    const onOnline = () => sync?.sender.kick();
    const onHide = () => {
      if (document.visibilityState !== "hidden") return;
      onBlur();
      void sync?.flushNow();
    };
    const onPageHide = () => void sync?.flushNow();
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
    window.addEventListener("online", onOnline);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("pointercancel", onUp, true);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("online", onOnline);
      void sync?.close();
      crops.dispose();
    };
  }, [route.canvas, route.chunk, status, clock, sceneData, drafts]);

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
  const open = initial !== null && initial !== "failed" && initial !== "missing";
  // Excalidraw is up before the scene arrives, but nothing may act on it until the scene is open:
  // a stroke or a rail tap in that window would be replaced by the scene when it lands.
  const liveApi = open ? api : null;
  useEffect(() => {
    if (!open) return;
    const refetch = () => void fetchDrafts(route.canvas).then((ops) => drafts.set(ops));
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const wire = wireRefresh(refresh, document);
    const tab = syncRef.current?.tabId ?? "";
    const live = new LiveDelta({
      origin: tab,
      isPenDown: () => penDown.current,
      apply: (els) => syncRef.current?.applyRemote(els),
      fetchSince: async (seq) => {
        const r = await fetch(`/documents/${encodeURIComponent(route.canvas)}/elements?since=${seq}`);
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      },
    });
    live.setSeq(syncRef.current?.loadedSeq ?? 0);
    liveRef.current = live;
    catchUpRef.current = () => void live.catchUp().then(() => void (live.drained && syncRef.current?.snapshot(live.lastSeq))) // a seq with queued (pen-down) rows is not applied yet;
    if (sceneReady.current) catchUpRef.current();
    const offWake = onVisible(document, () => void live.catchUp());
    // The server gates offer pushes on the pen and view (INK-130): scene units, view at most every 500 ms.
    const att = createAttention((a) => socket.sendAttention(a), () => performance.now());
    const viewNow = () => (apiRef.current ? toAttentionView(apiRef.current.getAppState()) : null);
    const sendView = () => att.view(viewNow());
    const releasePen = () => att.pen(false, viewNow()); // a pen-up that never arrives must not hold offers back
    const offAtt = apiReady.promise.then((api) => [
      api.onPointerDown((tool) => (tool.type === "freedraw" || tool.type === "eraser") && att.pen(true, viewNow())),
      api.onPointerUp(() => att.pen(false, viewNow())),
      api.onScrollChange(sendView),
    ]);
    const onHide = () => document.visibilityState === "hidden" && releasePen();
    window.addEventListener("pointercancel", releasePen, true);
    window.addEventListener("blur", releasePen);
    document.addEventListener("visibilitychange", onHide);
    const socket = new OpsSocket({
      url: `${scheme}://${window.location.host}/ws?document=${encodeURIComponent(route.canvas)}&device=${encodeURIComponent(tab)}`,
      onOp: (op) => measureOp(op),
      // op.placed carries no box, and /drafts is the one source for the card and the drag offset.
      onOpPlaced: refetch,
      // A save left chunks with stale crops: export them once the canvas is idle (INK-057).
      onChunksUpdated: () => {
        cropRef.current?.request();
        wire.onChunksUpdated();
      },
      // A push lost while the socket was down is gone, so the chunk list refetches on every connect.
      onConnection: (c) => {
        wire.onConnection(c);
        if (c) refetch(); // placed ops are replayed too, but a verdict made while down is only seen here
        if (c) void live.catchUp(); // a delta lost while the socket was down is gone
        if (c) publishQuestion(null); // pushes sent while the socket was down are lost
        if (c) void listOffers(route.canvas).then((r) => offerStore.set(r.offers, r.waiting, r.focus)).catch(() => {}); // same for offers
        if (c) att.view(viewNow(), true); // the server holds offers until it has seen the view
      },
      onQuestionUpdate: publishQuestion,
      onQuestionDelta: publishDelta,
      onSceneDelta: (d) => live.receive(d),
      onOfferCreated: offerStore.upsert,
      onOfferUpdated: offerStore.upsert,
      // Anything but placed leaves the canvas; an unaccept returns the op to placed with only this message.
      onOpUpdated: (m) => (m.status === "placed" ? refetch() : drafts.remove(m.op_id)),
      onOpError: (m) => console.warn("op refused by the server", m),
    });
    const cancel = gate.whenReady(() => socket.start());
    // A missing first change event must never leave the socket off.
    const fallback = window.setTimeout(() => gate.open(), 3000);
    return () => {
      window.clearTimeout(fallback);
      cancel();
      socket.dispose();
      window.removeEventListener("pointercancel", releasePen, true);
      window.removeEventListener("blur", releasePen);
      document.removeEventListener("visibilitychange", onHide);
      void offAtt.then((offs) => offs.forEach((off) => off()));
      wire.off();
      offWake();
      liveRef.current = null;
      catchUpRef.current = null;
    };
  }, [open, route.canvas, apiReady, refresh, unseen, gate, drafts, offerStore]);

  // The scene is a function of the placed-op list: add what is missing, drop what is gone, and
  // reveal a draft the first time it appears (a reload or reconnect replay must not pan).
  useEffect(() => {
    if (!liveApi) return;
    let known = new Set(drafts.ids());
    const run = () => {
      const scene = liveApi.getSceneElementsIncludingDeleted() as never as DraftElement[];
      const next = reconcile(scene, drafts.list());
      if (next !== scene) liveApi.updateScene({ elements: next as never, captureUpdate: CaptureUpdateAction.NEVER });
      for (const id of drafts.ids()) {
        if (known.has(id)) continue;
        lastPanAt.current = reveal(liveApi, id, { penDown: penDown.current, lastPanAt: lastPanAt.current }, unseen);
      }
      known = new Set(drafts.ids());
    };
    run();
    return drafts.subscribe(run);
  }, [liveApi, drafts, unseen]);

  const onChange = useCallback(
    (
      elements: readonly unknown[],
      appState: { scrollX: number; scrollY: number; zoom: { value: number }; cursorButton?: string; newElement?: unknown },
    ) => {
      // Set before any early return below, so every change event keeps it current.
      penDown.current = appState.cursorButton === "down" || appState.newElement != null;
      liveRef.current?.flush();
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
        catchUpRef.current?.();
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
    <Shell
      api={liveApi}
      title={initial === "missing" ? "Canvas not found" : title}
      status={<StatusSlot store={status} />}
      chunks={<><FingerToggle /><FocusToggle store={offerStore} canvas={route.canvas} /><ChunkToggle view={chunkView} /></>}
      overlays={
        <>
          {api && open && <TouchRouting api={api} />}
          {api && open && <FastInk api={api} />}
          {api && open && (
            <ChunkOverlay
              api={api}
              canvas={route.canvas}
              status={status}
              view={chunkView}
              ghost={ghostOpen && jump?.outcome === "orphaned" ? jump.chunk!.bounds : null}
              refresh={refresh}
            />
          )}
          {api && open && <OfferLayer api={api} canvas={route.canvas} store={offerStore} refresh={refresh} onOpenAsk={(id) => (setAskThread(id ?? null), setAskOpen(true))} />}
          {noticeOpen && jump && jumpNotice(jump) && <JumpNotice text={jumpNotice(jump)!} onClose={closeNotice} onExpire={expireNotice} />}
          {liveApi && <DraftBar api={liveApi} documentId={route.canvas} unseen={unseen} drafts={drafts} onOpenThread={(id) => {
            setAskThread(id);
            setAskOpen(true);
          }} />}
        </>
      }
      onAsk={() => (askOpen ? closeAsk() : setAskOpen(true))}
      askOpen={askOpen}
    >
      {(initial === "missing" || initial === "failed") && (
        <CanvasState kind={initial === "missing" ? "missing" : "error"} canvas={route.canvas} />
      )}
      {initial === null && <div className="ink-shell__loading" aria-hidden />}
      {open || initial === null ? <Canvas initialData={sceneData.promise} onApi={onApi} onChange={onChange} /> : null}
      {api && open && (
        <AskPanel api={api} canvas={route.canvas} open={askOpen} onClose={closeAsk} openThreadId={askThread} onThreadChange={setAskThread} draftOps={drafts.list()} />
      )}
    </Shell>
  );
}
