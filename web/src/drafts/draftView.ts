// Bring a new agent draft into view (INK-076, docs/decisions/0054). Pure view logic, no Excalidraw
// import: the callers read the scene and app state and apply the scroll themselves. Pan only; the
// zoom is never changed, because the user writes zoomed in.

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** width and height are screen px; scroll and zoom are Excalidraw's (screen = (scene + scroll) * zoom). */
export interface Viewport {
  scrollX: number;
  scrollY: number;
  zoom: number;
  width: number;
  height: number;
}

/** A pan this recent counts as the same batch: a second draft in it gets a chip, not another pan. */
export const BATCH_MS = 1500;
/** Screen px kept between the viewport edge and a draft larger than the view. */
export const MARGIN_PX = 40;

interface Located {
  id: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  points?: readonly (readonly number[])[];
  isDeleted?: boolean;
  customData?: Record<string, unknown>;
}

function extent(el: Located): Box {
  const pts = el.points;
  if (pts && pts.length > 0) {
    const xs = pts.map((p) => el.x + p[0]);
    const ys = pts.map((p) => el.y + p[1]);
    const x0 = Math.min(...xs);
    const y0 = Math.min(...ys);
    return { x: x0, y: y0, width: Math.max(...xs) - x0, height: Math.max(...ys) - y0 };
  }
  return { x: el.x, y: el.y, width: el.width ?? 0, height: el.height ?? 0 };
}

/** Bounds of the live elements tagged customData.op_id === opId; null when there are none. */
export function draftBox(els: readonly Located[], opId: string): Box | null {
  let out: { x0: number; y0: number; x1: number; y1: number } | null = null;
  for (const el of els) {
    if (el.isDeleted || el.customData?.op_id !== opId) continue;
    const b = extent(el);
    out ??= { x0: b.x, y0: b.y, x1: b.x + b.width, y1: b.y + b.height };
    out.x0 = Math.min(out.x0, b.x);
    out.y0 = Math.min(out.y0, b.y);
    out.x1 = Math.max(out.x1, b.x + b.width);
    out.y1 = Math.max(out.y1, b.y + b.height);
  }
  return out && { x: out.x0, y: out.y0, width: out.x1 - out.x0, height: out.y1 - out.y0 };
}

/** The visible part of the scene, in scene units. */
export function viewportBox(v: Viewport): Box {
  return { x: -v.scrollX, y: -v.scrollY, width: v.width / v.zoom, height: v.height / v.zoom };
}

/** At least half of the box (or of the viewport, if the box is bigger) must be on screen. */
export function inView(box: Box, v: Viewport): boolean {
  const view = viewportBox(v);
  const ox = Math.max(0, Math.min(box.x + box.width, view.x + view.width) - Math.max(box.x, view.x));
  const oy = Math.max(0, Math.min(box.y + box.height, view.y + view.height) - Math.max(box.y, view.y));
  const boxArea = Math.max(box.width * box.height, 1);
  const viewArea = view.width * view.height;
  return ox * oy >= 0.5 * Math.min(boxArea, viewArea);
}

/** The scroll that centres the box, or puts a box bigger than the view at a screen margin. */
export function panTarget(box: Box, v: Viewport): { scrollX: number; scrollY: number } {
  const m = MARGIN_PX / v.zoom;
  const axis = (start: number, size: number, viewLen: number) =>
    size + 2 * m <= viewLen ? -(start + size / 2 - viewLen / 2) : -(start - m);
  return {
    scrollX: axis(box.x, box.width, v.width / v.zoom),
    scrollY: axis(box.y, box.height, v.height / v.zoom),
  };
}

export type Reveal = "none" | "pan" | "chip";

/**
 * In view: nothing. Otherwise a pan, unless the pen is down or a pan happened within the batch
 * window, when the draft waits behind a chip (the user decides when to jump).
 */
export function planReveal(a: {
  box: Box;
  view: Viewport;
  penDown: boolean;
  lastPanAt: number | null;
  now: number;
}): Reveal {
  if (inView(a.box, a.view)) return "none";
  if (a.penDown) return "chip";
  if (a.lastPanAt !== null && a.now - a.lastPanAt < BATCH_MS) return "chip";
  return "pan";
}

/** Op ids whose draft was off-screen and not yet looked at. A small external store (see status.ts). */
export function createUnseen() {
  let current: readonly string[] = [];
  const listeners = new Set<() => void>();
  const set = (next: readonly string[]) => {
    if (next.length === current.length && next.every((id, i) => id === current[i])) return;
    current = next;
    listeners.forEach((l) => l());
  };
  return {
    ids: () => current,
    add(id: string) {
      if (!current.includes(id)) set([...current, id]);
    },
    remove(id: string) {
      if (current.includes(id)) set(current.filter((x) => x !== id));
    },
    prune(live: ReadonlySet<string>) {
      set(current.filter((id) => live.has(id)));
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}

export type Unseen = ReturnType<typeof createUnseen>;
