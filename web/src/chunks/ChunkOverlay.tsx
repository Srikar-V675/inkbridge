// Chunk boxes and ids drawn as plain DOM over the canvas. UI state only: nothing here touches the
// Excalidraw scene, so the overlay can never be autosaved (docs/decisions/0014). The merge and
// split actions only call the API (docs/decisions/0024); they never change elements either.
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { listChunks, toScreen, type Bounds, type Chunk, type View } from "./chunks";
import { chunkMark, connectorIds, overrideUi, planOverride, sendOverride, toggleChunk } from "./overrides";
import type { Refresh } from "../sync/chunkRefresh";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import type { ChunkView } from "./chunkView";
import "./ChunkOverlay.css";

type StatusStore = { get: () => { state: string }; subscribe: (l: () => void) => () => void };

// The refetch runs when the browser is idle, so it never competes with a pen stroke (INK-079).
const whenIdle = (f: () => void) =>
  typeof requestIdleCallback === "function" ? requestIdleCallback(f, { timeout: 2000 }) : setTimeout(f, 0);

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

/** Selected element ids, updated only when the selection itself changes (not on every stroke point). */
function useSelection(api: ExcalidrawImperativeAPI): string[] {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(
    () =>
      api.onChange((_elements, appState) => {
        const ids = Object.keys(appState.selectedElementIds).filter((id) => appState.selectedElementIds[id]);
        ids.sort();
        setSelected((prev) => (prev.length === ids.length && prev.every((id, i) => id === ids[i]) ? prev : ids));
      }),
    [api],
  );
  return selected;
}

/**
 * Active chunks while `on`, refetched when `refresh` fires (after a save, a chunk push, a socket
 * reconnect or the tablet waking up; the server re-derives chunks on save).
 * Rows are tagged with the `session` (one per time the overlay is turned on) they were fetched in,
 * so a reload keeps the old boxes until the new list arrives, but turning the overlay on again
 * never shows a list from before.
 */
function useChunks(
  canvas: string,
  on: boolean,
  session: number,
  status: StatusStore,
  refresh: Refresh,
): [Chunk[], () => void] {
  const [chunks, setChunks] = useState<{ session: number; rows: Chunk[] }>({ session: -1, rows: [] });
  const [generation, setGeneration] = useState(0);
  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  useEffect(() => {
    if (!on) return;
    // Saves can overlap the fetch: only the latest request may set the list. A deferred or
    // in-flight load from an ended effect (canvas or session changed, unmounted) must not set it.
    let latest = 0;
    let disposed = false;
    const load = () => {
      if (disposed) return;
      const n = ++latest;
      void listChunks(canvas).then((rows) => !disposed && n === latest && setChunks({ session, rows }));
    };
    load();
    let last = status.get().state;
    const unsubscribe = status.subscribe(() => {
      const now = status.get().state;
      if (now === "saved" && last !== "saved") refresh.fire();
      last = now;
    });
    const offRefresh = refresh.subscribe(() => whenIdle(load));
    return () => {
      disposed = true;
      unsubscribe();
      offRefresh();
    };
  }, [canvas, on, session, status, generation, refresh]);
  return [on && chunks.session === session ? chunks.rows : [], reload];
}

/** "Merge chunks" and "Split selection" for the current selection, above the zoom control. */
function OverrideActions(props: {
  api: ExcalidrawImperativeAPI;
  canvas: string;
  selected: string[];
  chunks: Chunk[];
  onDone: () => void;
}) {
  const { api, canvas, selected, chunks, onDone } = props;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Read the scene only when the selection or the list changes, never per stroke point.
  const connectors = useMemo(
    () => (selected.length > 0 ? connectorIds(api.getSceneElements() as never) : new Set<string>()),
    [api, selected],
  );
  const plan = planOverride(selected, chunks, connectors);
  const run = async () => {
    setBusy(true);
    const r = await sendOverride(canvas, plan);
    setBusy(false);
    setMessage(r.ok ? (plan.kind === "merge" ? `Merged into ${r.ids[0]}` : `Split into ${r.ids.join(" and ")}`) : r.message);
    onDone(); // refresh either way: a refusal usually means the list was stale
  };
  const ui = overrideUi(plan);
  const merge = ui.canMerge && !busy;
  const split = ui.canSplit && !busy;
  return (
    <Card className="ink-chunk-actions">
      {message && <p role="status">{message}</p>}
      <p data-testid="override-hint">{ui.hint}</p>
      <div className="ink-chunk-actions__row">
        <Button variant="secondary" disabled={!merge} onClick={() => void run()}>
          Merge chunks
        </Button>
        <Button variant="secondary" disabled={!split} onClick={() => void run()}>
          Split selection
        </Button>
      </div>
    </Card>
  );
}

const box = (b: Bounds, v: View): React.CSSProperties => {
  const s = toScreen(b, v);
  return { position: "absolute", left: s.left, top: s.top, width: s.width, height: s.height, boxSizing: "border-box" };
};

/** The quiet "Chunks" toggle that lives in the top bar; the overlay reads the same store. */
export function ChunkToggle({ view }: { view: ChunkView }) {
  const { on } = useSyncExternalStore(view.subscribe, view.get);
  return (
    <Button variant="quiet" className="ink-chunk-toggle" aria-pressed={on} onClick={view.toggle}>
      Chunks
    </Button>
  );
}

export function ChunkOverlay(props: {
  api: ExcalidrawImperativeAPI;
  canvas: string;
  status: StatusStore;
  /** On/off and session, shared with the top bar toggle. */
  view: ChunkView;
  /** Old bounds of an orphaned deep-linked chunk, shown until the notice is dismissed. */
  ghost: Bounds | null;
  refresh: Refresh;
}) {
  const { api, canvas, status, view, ghost, refresh } = props;
  const { on, session } = useSyncExternalStore(view.subscribe, view.get);
  const scroll = useView(api);
  const selected = useSelection(api);
  const [chunks, reload] = useChunks(canvas, on, session, status, refresh);
  // Read the scene only when the selection or the list changes, never per stroke point.
  const connectors = useMemo(
    () => (on ? connectorIds(api.getSceneElements() as never) : new Set<string>()),
    [api, on, selected, chunks],
  );
  // Tapping a chip writes the chunk's live ink into Excalidraw's own selection; no element changes.
  const select = useCallback(
    (c: Chunk) => {
      const ids = toggleChunk(selected, c, api.getSceneElements() as never);
      api.updateScene({ appState: { selectedElementIds: Object.fromEntries(ids.map((id) => [id, true])) as never } });
    },
    [api, selected],
  );

  return (
    <>
      {(on || ghost) && (
        <div data-testid="chunk-overlay" className="ink-chunk-layer">
          {on &&
            chunks.map((c) => {
              const mark = chunkMark(selected, c, connectors);
              return (
                <div
                  key={c.id}
                  data-chunk-id={c.id}
                  data-pinned={c.pinned ? "true" : undefined}
                  data-selected={mark}
                  className={`ink-chunk ink-chunk--${mark}${c.pinned ? " ink-chunk--pinned" : ""}`}
                  style={box(c.bounds, scroll)}
                >
                  {/* Above the box, or inside it when the box touches the top edge. */}
                  <button
                    type="button"
                    className="ink-chunk-tab"
                    aria-pressed={mark === "full"}
                    data-testid={`chunk-tab-${c.id}`}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => select(c)}
                    style={{ top: toScreen(c.bounds, scroll).top < 44 ? 0 : -44 }}
                  >
                    <span className="ink-chunk-tab__label">
                      {c.id}
                      {c.pinned ? " · manual" : ""}
                    </span>
                  </button>
                </div>
              );
            })}
          {ghost && <div data-testid="chunk-ghost" aria-hidden className="ink-chunk-ghost" style={box(ghost, scroll)} />}
        </div>
      )}
      {on && <OverrideActions api={api} canvas={canvas} selected={selected} chunks={chunks} onDone={reload} />}
    </>
  );
}
