// Fast ink (INK-181, decision 0076): draw the stroke in progress on our own canvas in the pointermove
// handler itself, from every pen sample, instead of waiting for Excalidraw. Excalidraw handles a move
// in the next animation frame and draws the stroke one frame after that, so its ink trails the pen;
// this layer shows the same outline (same perfect-freehand version and options, same points plus the
// samples Excalidraw has not taken yet) at once, and is cleared when Excalidraw has drawn the
// finished stroke underneath. Framework-free; the node tests drive it with plain objects.
import { getStroke } from "perfect-freehand";
import type { PenSample, PenSamples } from "./penSamples.ts";

export interface FreedrawLike {
  id: string;
  type: string;
  x: number;
  y: number;
  angle: number;
  opacity: number;
  strokeColor: string;
  strokeWidth: number;
  simulatePressure: boolean;
  points: readonly (readonly number[])[];
  pressures: readonly number[];
  lastCommittedPoint?: unknown;
}

export interface ViewLike {
  scrollX: number;
  scrollY: number;
  zoom: number;
  offsetLeft: number;
  offsetTop: number;
}

// Excalidraw's getFreeDrawSvgPath after the INK-062 pen-feel patch (web/patches); penFeel.test.ts
// fails if the patch and these drift apart.
export const FREEDRAW = { sizePerWidth: 4.25, thinning: 0.3, smoothing: 0.5, streamline: 0.2 } as const;

export function strokeOptions(el: FreedrawLike) {
  return {
    simulatePressure: el.simulatePressure,
    size: el.strokeWidth * FREEDRAW.sizePerWidth,
    thinning: FREEDRAW.thinning,
    smoothing: FREEDRAW.smoothing,
    streamline: FREEDRAW.streamline,
    easing: (t: number) => Math.sin((t * Math.PI) / 2),
    last: !!el.lastCommittedPoint,
  };
}

/** Only an opaque, unrotated stroke still being drawn: a see-through one (the highlighter) would show darker where both layers overlap. */
export function canDraw(el: FreedrawLike | null | undefined): el is FreedrawLike {
  return !!el && el.type === "freedraw" && el.opacity >= 100 && el.angle === 0 && !el.lastCommittedPoint;
}

/** The stroke's points with the samples Excalidraw has not taken yet, the way its patched move handler will add them. */
export function inputPoints(el: FreedrawLike, pending: readonly PenSample[], v: ViewLike): number[][] {
  const pts = el.points.map((p) => [p[0], p[1]]);
  const pr = [...el.pressures];
  for (const s of pending) {
    const dx = (s.clientX - v.offsetLeft) / v.zoom - v.scrollX - el.x;
    const dy = (s.clientY - v.offsetTop) / v.zoom - v.scrollY - el.y;
    const last = pts[pts.length - 1];
    if (last && last[0] === dx && last[1] === dy) continue;
    pts.push([dx, dy]);
    if (!el.simulatePressure) pr.push(s.pressure);
  }
  if (el.simulatePressure) return pts;
  return pts.length ? pts.map(([x, y], i) => [x, y, pr[i]]) : [[0, 0, 0.5]];
}

export function outline(el: FreedrawLike, pending: readonly PenSample[], v: ViewLike): number[][] {
  return getStroke(inputPoints(el, pending, v), strokeOptions(el));
}

type PathCtx = {
  beginPath(): void;
  moveTo(x: number, y: number): void;
  quadraticCurveTo(cx: number, cy: number, x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
};

/** The path Excalidraw's getSvgPathFromStroke builds ("M p0 Q p0 m01 p1 m12 ... L p0 Z"), as canvas calls. */
export function tracePath(ctx: PathCtx, pts: readonly number[][]) {
  ctx.beginPath();
  if (pts.length === 0) return;
  const mid = (a: readonly number[], b: readonly number[]) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const max = pts.length - 1;
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 0; i <= max; i++) {
    const m = mid(pts[i], pts[i === max ? 0 : i + 1]);
    ctx.quadraticCurveTo(pts[i][0], pts[i][1], m[0], m[1]);
  }
  ctx.lineTo(pts[0][0], pts[0][1]);
  ctx.closePath();
}

type Box = [number, number, number, number]; // x0, y0, x1, y1

/** The outline's bounds on the canvas in device pixels, grown by 2 px for anti-aliasing and rounded out. */
export function deviceBox(pts: readonly number[][], k: number, ox: number, oy: number): Box {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of pts) {
    if (p[0] < x0) x0 = p[0];
    if (p[0] > x1) x1 = p[0];
    if (p[1] < y0) y0 = p[1];
    if (p[1] > y1) y1 = p[1];
  }
  if (!Number.isFinite(x0)) return [0, 0, 0, 0];
  return [Math.floor(ox + k * x0) - 2, Math.floor(oy + k * y0) - 2, Math.ceil(ox + k * x1) + 2, Math.ceil(oy + k * y1) + 2];
}

const union = (a: Box, b: Box): Box => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];

export interface Surface {
  /** Size the canvas to the Excalidraw canvas (CSS pixels at this position) and return its 2D context. */
  prepare(left: number, top: number, width: number, height: number, dpr: number): CanvasRenderingContext2D | null;
  clear(): void;
}

export interface FastInkDeps {
  win: {
    addEventListener(t: string, cb: (e: PointerEvent) => void, o: { capture: boolean; passive: boolean }): void;
    removeEventListener(t: string, cb: (e: PointerEvent) => void, o: { capture: boolean }): void;
  };
  samples: PenSamples;
  /** The stroke Excalidraw is drawing (appState.newElement) and the view. */
  state(): { newElement: FreedrawLike | null; view: ViewLike; width: number; height: number };
  /** Which pointers may draw: pen and mouse always, a finger only with "Finger draws" on. */
  mayDraw(pointerType: string): boolean;
  isCanvas(target: unknown): boolean;
  surface: Surface;
  dpr(): number;
  frame(cb: () => void): void;
  /** Frames to wait for Excalidraw to draw the finished stroke before the layer is cleared. */
  settleFrames?: number;
}

export function installFastInk(d: FastInkDeps): () => void {
  let pointer: number | null = null; // the pointer drawing the current stroke
  let drawn = false;
  let generation = 0;
  let last: Box | null = null; // what the last draw painted, in device pixels
  const settle = d.settleFrames ?? 2;

  const clearNow = () => {
    if (drawn) d.surface.clear();
    drawn = false;
    last = null;
  };

  const down = (e: PointerEvent) => {
    if (pointer !== null || !d.mayDraw(e.pointerType) || !d.isCanvas(e.target)) return;
    pointer = e.pointerId;
    generation++;
  };

  const move = (e: PointerEvent) => {
    if (e.pointerId !== pointer) return;
    const s = d.state();
    if (!canDraw(s.newElement)) return clearNow();
    const pts = outline(s.newElement, d.samples.peek(e.pointerId), s.view);
    const v = s.view;
    const dpr = d.dpr();
    const ctx = d.surface.prepare(v.offsetLeft, v.offsetTop, s.width, s.height, dpr);
    if (!ctx) return;
    const k = dpr * v.zoom;
    const ox = k * (s.newElement.x + v.scrollX);
    const oy = k * (s.newElement.y + v.scrollY);
    // Clear and paint only the stroke's box (device pixels), not the whole canvas, on every move.
    const box = deviceBox(pts, k, ox, oy);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const clear = last ? union(last, box) : box;
    ctx.clearRect(clear[0], clear[1], clear[2] - clear[0], clear[3] - clear[1]);
    last = box;
    ctx.setTransform(k, 0, 0, k, ox, oy);
    ctx.fillStyle = s.newElement.strokeColor;
    tracePath(ctx, pts);
    ctx.fill();
    drawn = true;
  };

  // Keep the fast ink until Excalidraw has finalised the stroke and drawn it, then a frame or two more.
  const up = (e: PointerEvent) => {
    if (e.pointerId !== pointer) return;
    pointer = null;
    if (!drawn) return;
    const mine = generation;
    let waited = 0;
    let after = 0;
    const step = () => {
      if (generation !== mine) return; // a new stroke started: its first draw replaces this one
      if (d.state().newElement && waited++ < 30) return d.frame(step);
      if (after++ < settle) return d.frame(step);
      clearNow();
    };
    d.frame(step);
  };

  const opts = { capture: true, passive: true };
  d.win.addEventListener("pointerdown", down, opts);
  d.win.addEventListener("pointermove", move, opts);
  d.win.addEventListener("pointerup", up, opts);
  d.win.addEventListener("pointercancel", up, opts);
  return () => {
    d.win.removeEventListener("pointerdown", down, { capture: true });
    d.win.removeEventListener("pointermove", move, { capture: true });
    d.win.removeEventListener("pointerup", up, { capture: true });
    d.win.removeEventListener("pointercancel", up, { capture: true });
    generation++;
    clearNow();
  };
}
