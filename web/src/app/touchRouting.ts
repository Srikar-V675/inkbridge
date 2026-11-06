// Pure routing for touch input (INK-173, docs/decisions/0072): one finger pans, two pinch, the pen
// draws. No React, DOM or Excalidraw imports, so Node tests pin it.
import { ZOOM_MAX, ZOOM_MIN } from "./shellLogic.ts";

export type Route = "pass" | "pan" | "ignore";
export interface RouteInput {
  pointerType: string;
  tool: string; // appState.activeTool.type
  penActive: boolean;
  fingerDraws: boolean;
  overElement: boolean; // only read for the selection tool
  panning: boolean; // a finger of ours is already panning
  touchPassed: boolean; // a finger already went to Excalidraw
}

/** Where a pointerdown goes. Only touch is ever taken from Excalidraw. */
export function routePointer(i: RouteInput): Route {
  if (i.pointerType !== "touch") return "pass";
  if (i.penActive) return "ignore";
  if (i.fingerDraws || i.touchPassed) return "pass";
  if (i.panning) return "pan";
  if (i.tool === "text") return "pass";
  if (i.tool === "selection") return i.overElement ? "pass" : "pan";
  return "pan";
}

export const PEN_GRACE_MS = 600;
/** A pen "down" with no pen event at all for this long is a lost pen-up (hover or stroke keeps sending moves). */
export const PEN_DOWN_MAX_MS = 3000;
/** Pen proximity: down (while events keep coming), or any pen event within the grace window (hover keeps sending moves). */
export function createPenTracker(now: () => number, graceMs = PEN_GRACE_MS, downMaxMs = PEN_DOWN_MAX_MS) {
  let down = false;
  let last = -Infinity;
  return {
    observe(e: { type: string; pointerType: string }) {
      if (e.pointerType !== "pen") return;
      last = now();
      if (e.type === "pointerdown") down = true;
      if (e.type === "pointerup" || e.type === "pointercancel" || e.type === "lostpointercapture") down = false;
    },
    active: () => now() - last < graceMs || (down && now() - last < downMaxMs),
    /** Forget the pen (window blur, page hidden): its pointerup may never arrive. */
    reset() {
      down = false;
      last = -Infinity;
    },
  };
}

/** The Excalidraw interactive canvas, the only place touch is routed. Structural so Node can test it. */
export function isExcalidrawCanvas(t: unknown): boolean {
  const n = t as { tagName?: string; classList?: { contains(c: string): boolean }; closest?(s: string): unknown } | null;
  return !!n && n.tagName === "CANVAS" && !!n.classList?.contains("interactive") && !!n.closest?.(".excalidraw");
}

export interface BoxElement { x: number; y: number; width: number; height: number; isDeleted?: boolean }
/** True if (x, y) in scene units is inside any live element's box grown by pad (rotation ignored: a finger is coarse). */
export function hitsElement(els: readonly BoxElement[], x: number, y: number, pad: number): boolean {
  return els.some((e) => {
    if (e.isDeleted) return false;
    const x0 = Math.min(e.x, e.x + e.width);
    const y0 = Math.min(e.y, e.y + e.height);
    return x >= x0 - pad && x <= x0 + Math.abs(e.width) + pad && y >= y0 - pad && y <= y0 + Math.abs(e.height) + pad;
  });
}

export interface Pt { x: number; y: number } // viewport coordinates (client minus offsetLeft/Top)
export interface ViewState { scrollX: number; scrollY: number; zoom: number }
export interface Anchor { zoom: number; dist: number; scene: Pt }
const centre = (ps: readonly Pt[]): Pt => ({ x: ps.reduce((s, p) => s + p.x, 0) / ps.length, y: ps.reduce((s, p) => s + p.y, 0) / ps.length });
const spread = (ps: readonly Pt[]) => (ps.length < 2 ? 0 : Math.hypot(ps[1].x - ps[0].x, ps[1].y - ps[0].y));
const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

/** Freeze the scene point under the fingers' centre and the zoom at the start of (or a change in) a gesture. */
export function anchorFor(v: ViewState, pts: readonly Pt[]): Anchor {
  const c = centre(pts);
  return { zoom: v.zoom, dist: spread(pts), scene: { x: c.x / v.zoom - v.scrollX, y: c.y / v.zoom - v.scrollY } };
}

/** The view that keeps the anchored scene point under the fingers' centre; two fingers scale by their spread. */
export function viewFor(a: Anchor, pts: readonly Pt[]): ViewState {
  const c = centre(pts);
  const zoom = pts.length >= 2 && a.dist > 0 ? clampZoom(a.zoom * (spread(pts) / a.dist)) : a.zoom;
  return { zoom, scrollX: c.x / zoom - a.scene.x, scrollY: c.y / zoom - a.scene.y };
}

/** appState patch for the "Finger draws" setting. penDetected stops the first pen contact flipping penMode back. */
export const penPatch = (fingerDraws: boolean) => ({ penMode: !fingerDraws, penDetected: fingerDraws });
