// Chunk boxes and ids drawn as plain DOM over the canvas. UI state only: nothing here touches the
// Excalidraw scene, so the overlay can never be autosaved (docs/decisions/0014). The merge and
// split actions only call the API (docs/decisions/0024); they never change elements either.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { listChunks, toScreen, type Bounds, type Chunk, type View } from "./chunks";
import { chunkMark, connectorIds, overrideUi, planOverride, sendOverride, toggleChunk } from "./overrides";

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
 * Active chunks while `on`, refetched after every save (the server re-derives chunks on save).
 * Rows are tagged with the `session` (one per time the overlay is turned on) they were fetched in,
 * so a reload keeps the old boxes until the new list arrives, but turning the overlay on again
 * never shows a list from before.
 */
function useChunks(
  canvas: string,
  on: boolean,
  session: number,
  status: StatusStore,
): [Chunk[], () => void] {
  const [chunks, setChunks] = useState<{ session: number; rows: Chunk[] }>({ session: -1, rows: [] });
  const [generation, setGeneration] = useState(0);
  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  useEffect(() => {
    if (!on) return;
    // Saves can overlap the fetch: only the latest request may set the list.
    let latest = 0;
    const load = () => {
      const n = ++latest;
      void listChunks(canvas).then((rows) => n === latest && setChunks({ session, rows }));
    };
    load();
    let last = status.get().state;
    const unsubscribe = status.subscribe(() => {
      const now = status.get().state;
      if (now === "saved" && last !== "saved") load();
      last = now;
    });
    return () => {
      latest = -1;
      unsubscribe();
    };
  }, [canvas, on, session, status, generation]);
  return [on && chunks.session === session ? chunks.rows : [], reload];
}

const actionButton = (enabled: boolean): React.CSSProperties => ({
  minHeight: 44,
  padding: "8px 14px",
  borderRadius: 6,
  border: "1px solid #ced4da",
  font: "12px system-ui, sans-serif",
  background: "#fff",
  color: enabled ? "#202124" : "#adb5bd",
  opacity: enabled ? 1 : 0.5,
});

/** "Merge chunks" and "Split selection" for the current selection, next to the overlay toggle. */
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
    <div
      style={{
        position: "absolute",
        right: 12,
        bottom: 104,
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 6,
        maxWidth: "calc(100% - 24px)",
      }}
    >
      {message && (
        <div role="status" style={{ font: "12px system-ui, sans-serif", background: "#fff", padding: "2px 8px", borderRadius: 4 }}>
          {message}
        </div>
      )}
      <div data-testid="override-hint" style={{ font: "12px system-ui, sans-serif", background: "#fff", padding: "2px 8px", borderRadius: 4 }}>
        {ui.hint}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" disabled={!merge} onClick={() => void run()} style={actionButton(merge)}>
          Merge chunks
        </button>
        <button type="button" disabled={!split} onClick={() => void run()} style={actionButton(split)}>
          Split selection
        </button>
      </div>
    </div>
  );
}

const box = (b: Bounds, v: View): React.CSSProperties => {
  const s = toScreen(b, v);
  return { position: "absolute", left: s.left, top: s.top, width: s.width, height: s.height, boxSizing: "border-box" };
};

/** The label chip is the tap target: big enough for a finger, the only part of a box that takes input. */
const chip: React.CSSProperties = {
  position: "absolute",
  left: -1,
  display: "flex",
  alignItems: "center",
  minWidth: 44,
  minHeight: 32,
  padding: "0 6px",
  margin: 0,
  border: 0,
  font: "11px ui-monospace, monospace",
  whiteSpace: "nowrap",
  background: "#1971c2",
  color: "#fff",
  borderRadius: "3px 3px 0 0",
  pointerEvents: "auto",
  touchAction: "manipulation",
  cursor: "pointer",
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
  const [session, setSession] = useState(0);
  const view = useView(api);
  const selected = useSelection(api);
  const [chunks, reload] = useChunks(canvas, on, session, status);
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
        <div
          data-testid="chunk-overlay"
          style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 4 }}
        >
          {on &&
            chunks.map((c) => {
              const mark = chunkMark(selected, c, connectors);
              const edge =
                mark === "full"
                  ? "3px solid #e8590c"
                  : mark === "partial"
                    ? "1.5px dashed #e8590c"
                    : `${c.pinned ? 2.5 : 1.5}px solid #1971c2`;
              return (
                <div
                  key={c.id}
                  data-chunk-id={c.id}
                  data-pinned={c.pinned ? "true" : undefined}
                  data-selected={mark}
                  style={{
                    ...box(c.bounds, view),
                    border: edge,
                    background: mark === "full" ? "rgba(232,89,12,0.12)" : undefined,
                  }}
                >
                  {/* Above the box, or inside it when the box touches the top edge. */}
                  <button
                    type="button"
                    aria-pressed={mark === "full"}
                    data-testid={`chunk-tab-${c.id}`}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => select(c)}
                    style={{ ...chip, top: toScreen(c.bounds, view).top < 32 ? 0 : -32 }}
                  >
                    {c.id}
                    {c.pinned ? " · manual" : ""}
                  </button>
                </div>
              );
            })}
          {ghost && (
            <div
              data-testid="chunk-ghost"
              aria-hidden
              style={{ ...box(ghost, view), border: "2px dashed #e8590c" }}
            />
          )}
        </div>
      )}
      {on && <OverrideActions api={api} canvas={canvas} selected={selected} chunks={chunks} onDone={reload} />}
      <button
        type="button"
        aria-pressed={on}
        onClick={() => {
          if (!on) setSession((s) => s + 1);
          setOn(!on);
        }}
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
