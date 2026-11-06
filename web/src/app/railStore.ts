// Tool, pen colour and zoom store over the Excalidraw API (INK-117, docs/decisions/0066).
// useSyncExternalStore reads it, and get() returns the same object until a shown field changes,
// so a stroke (hundreds of onChange calls) never re-renders the rail.
import {
  colourNeedsPen, nextZoom, penIndex, railTool, toolTap, undoKey, zoomAbout, type RailTool,
} from "./shellLogic.ts";

export interface RailSnapshot {
  tool: RailTool | null;
  pen: number; // index into the pen colours, -1 if the current colour is none of them
  zoom: number;
}

interface RailState {
  isLoading?: boolean;
  selectedElementIds?: Record<string, boolean>;
  activeTool: { type: string };
  currentItemOpacity: number;
  currentItemStrokeColor: string;
  scrollX: number;
  scrollY: number;
  zoom: { value: number };
  width: number;
  height: number;
}

export interface RailApi {
  getAppState(): RailState;
  onChange(cb: (elements: readonly unknown[], appState: RailState) => void): () => void;
  setActiveTool(tool: { type: string }): void;
  updateScene(scene: { appState: Record<string, unknown>; captureUpdate: unknown }): void;
}

export interface RailEnv {
  /** CaptureUpdateAction.NEVER: these changes are not undo steps. Injected so Node tests need not load Excalidraw. */
  never: unknown;
  mac: boolean;
  container: () => { dispatchEvent(e: Event): boolean } | null;
  makeKey: (init: KeyboardEventInit) => Event;
  /** requestAnimationFrame and its cancel, to wait out Excalidraw's async initialData. */
  frame: (cb: () => void) => () => void;
}

const MAX_WAIT_FRAMES = 300; // give up waiting for Excalidraw to finish loading after about 5 s

export function createRailStore(api: RailApi, pens: readonly string[], env: RailEnv) {
  const listeners = new Set<() => void>();
  const read = (): RailSnapshot => {
    const a = api.getAppState();
    return { tool: railTool(a), pen: penIndex(a.currentItemStrokeColor, pens), zoom: a.zoom.value };
  };
  const scene = (appState: Record<string, unknown>) => api.updateScene({ appState, captureUpdate: env.never });

  let snap = read();
  const refresh = () => {
    const n = read();
    if (n.tool === snap.tool && n.pen === snap.pen && n.zoom === snap.zoom) return;
    snap = n;
    listeners.forEach((l) => l());
  };
  const offChange = api.onChange(refresh);

  // The pen is the starting tool, in charcoal. Excalidraw applies initialData asynchronously after
  // its API handle exists and would overwrite this, so wait until it has finished loading.
  let cancelFrame = () => {};
  let frames = 0;
  const begin = () => {
    if (api.getAppState().isLoading && frames++ < MAX_WAIT_FRAMES) {
      cancelFrame = env.frame(begin);
      return;
    }
    // A deep link may already have selected a chunk; picking the pen would clear that selection.
    const selected = Object.values(api.getAppState().selectedElementIds ?? {}).some(Boolean);
    if (!selected) api.setActiveTool({ type: "freedraw" });
    scene({ currentItemStrokeColor: pens[0] });
    refresh();
  };
  begin();

  const key = (kind: "undo" | "redo") => env.container()?.dispatchEvent(env.makeKey(undoKey(kind, env.mac)));

  return {
    get: () => snap,
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    tap(tool: RailTool) {
      const { tool: t, patch } = toolTap(tool, api.getAppState().activeTool.type);
      api.setActiveTool(t);
      if (Object.keys(patch).length) scene(patch);
      refresh();
    },
    setPen(i: number) {
      if (colourNeedsPen(api.getAppState().activeTool.type)) api.setActiveTool({ type: "freedraw" });
      scene({ currentItemStrokeColor: pens[i] });
      refresh();
    },
    zoomBy(dir: 1 | -1) {
      const a = api.getAppState();
      const next = nextZoom(a.zoom.value, dir);
      const z = zoomAbout({ scrollX: a.scrollX, scrollY: a.scrollY, zoom: a.zoom.value, width: a.width, height: a.height }, next);
      scene({ zoom: { value: z.zoom }, scrollX: z.scrollX, scrollY: z.scrollY });
      refresh();
    },
    undo: () => key("undo"),
    redo: () => key("redo"),
    dispose() {
      cancelFrame();
      offChange();
    },
  };
}
