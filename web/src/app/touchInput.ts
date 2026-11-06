// Window-level pointer router (INK-173, docs/decisions/0072). In the capture phase it takes touch
// pointers away from Excalidraw when they should pan or be ignored, and writes the view itself.
// Pen and mouse events are never stopped, so pen strokes and laptop use are unchanged.
import {
  anchorFor, createPenTracker, hitsElement, routePointer, viewFor,
  type Anchor, type BoxElement, type Pt, type ViewState,
} from "./touchRouting.ts";

export interface PtrEvent {
  type: string;
  pointerType: string;
  pointerId: number;
  clientX: number;
  clientY: number;
  target: unknown;
  stopPropagation(): void;
}

export interface TouchDeps {
  win: {
    addEventListener(t: string, cb: (e: PtrEvent) => void, o?: boolean): void;
    removeEventListener(t: string, cb: (e: PtrEvent) => void, o?: boolean): void;
  };
  isCanvas(target: unknown): boolean; // the Excalidraw interactive canvas only
  tool(): string; // api.getAppState().activeTool.type
  view(): ViewState & { offsetLeft: number; offsetTop: number };
  setView(v: ViewState): void; // api.updateScene({ appState, captureUpdate: NEVER })
  elements(): readonly BoxElement[]; // api.getSceneElements()
  fingerDraws(): boolean;
  now(): number;
  schedule(cb: () => void): () => void; // requestAnimationFrame / cancel; tests run it synchronously
}

const EVENTS = ["pointerdown", "pointermove", "pointerup", "pointercancel"] as const;
const HIT_PAD_PX = 16; // a finger is coarse: grow element boxes by this many screen pixels

export function installTouchInput(d: TouchDeps): () => void {
  const pen = createPenTracker(d.now);
  const pan = new Map<number, Pt>();
  const passed = new Set<number>();
  const ignored = new Set<number>();
  let anchor: Anchor | null = null;
  let cancelFrame: (() => void) | null = null;
  let scheduled = false;
  let dirty = false;

  const write = () => {
    scheduled = false;
    if (!dirty || !anchor) return;
    dirty = false;
    d.setView(viewFor(anchor, [...pan.values()]));
  };
  const flush = () => {
    if (scheduled) cancelFrame?.();
    write();
  };
  const reanchor = () => {
    anchor = pan.size ? anchorFor(d.view(), [...pan.values()]) : null;
  };
  const endPan = () => {
    flush();
    for (const id of pan.keys()) ignored.add(id);
    pan.clear();
    anchor = null;
    dirty = false;
  };
  const point = (e: PtrEvent): Pt => {
    const v = d.view();
    return { x: e.clientX - v.offsetLeft, y: e.clientY - v.offsetTop };
  };

  const onEvent = (e: PtrEvent) => {
    if (e.pointerType === "pen") {
      pen.observe(e);
      if (e.type === "pointerdown") endPan();
      return;
    }
    if (e.pointerType !== "touch") return;
    const id = e.pointerId;

    if (e.type === "pointerdown") {
      if (!d.isCanvas(e.target)) return;
      const v = d.view();
      const p = point(e);
      const tool = d.tool();
      const route = routePointer({
        pointerType: "touch",
        tool,
        penActive: pen.active(),
        fingerDraws: d.fingerDraws(),
        overElement: tool === "selection" && hitsElement(d.elements(), p.x / v.zoom - v.scrollX, p.y / v.zoom - v.scrollY, HIT_PAD_PX / v.zoom),
        panning: pan.size > 0,
        touchPassed: passed.size > 0,
      });
      if (route === "pass") passed.add(id);
      else if (route === "ignore") {
        e.stopPropagation();
        ignored.add(id);
      } else {
        e.stopPropagation();
        flush();
        pan.set(id, p);
        reanchor();
      }
      return;
    }

    if (e.type === "pointermove") {
      if (pan.has(id)) {
        e.stopPropagation();
        pan.set(id, point(e));
        dirty = true;
        if (!scheduled) {
          scheduled = true;
          cancelFrame = d.schedule(write);
        }
      } else if (ignored.has(id)) e.stopPropagation();
      return;
    }

    // pointerup, pointercancel
    if (pan.has(id)) {
      e.stopPropagation();
      pan.set(id, point(e));
      dirty = true;
      flush();
      pan.delete(id);
      reanchor();
    } else if (ignored.has(id)) {
      e.stopPropagation();
      ignored.delete(id);
    }
    passed.delete(id);
  };

  for (const t of EVENTS) d.win.addEventListener(t, onEvent, true);
  return () => {
    for (const t of EVENTS) d.win.removeEventListener(t, onEvent, true);
    if (scheduled) cancelFrame?.();
    scheduled = false;
  };
}

/** Run apply once Excalidraw has finished loading its initialData (it holds back onChange until then). */
export function whenLoaded(
  api: { getAppState(): { isLoading?: boolean } },
  frame: (cb: () => void) => () => void,
  apply: () => void,
  maxFrames = 300,
): () => void {
  let cancel = () => {};
  let frames = 0;
  let live = true;
  const step = () => {
    if (!live) return;
    if (api.getAppState().isLoading && frames++ < maxFrames) {
      cancel = frame(step);
      return;
    }
    apply();
  };
  step();
  return () => {
    live = false;
    cancel();
  };
}
