// Pure logic for the app shell (INK-117, docs/decisions/0066): paper dots, zoom, rail tools.
// No React, DOM or Excalidraw imports, so the Node test runner can load it.

export const TILE = 36; // scene units between dots (INK-170: finer than the Main board's 24, decision 0074)
export const MIN_DOT_PX = 10; // below this, double the spacing

/** Smallest TILE * 2^n whose on-screen size is at least MIN_DOT_PX. */
export function dotStep(zoom: number): number {
  let step = TILE;
  while (step * zoom < MIN_DOT_PX) step *= 2;
  return step;
}

export interface PaperView {
  scrollX: number;
  scrollY: number;
  zoom: number;
}

/** CSS for the dot layer. A dot sits at the centre of each tile, so scene point (k*step + step/2) shows a dot. */
export function paperDots(v: PaperView): { size: number; x: number; y: number } {
  const size = dotStep(v.zoom) * v.zoom;
  const mod = (n: number) => ((n % size) + size) % size;
  return { size, x: mod(v.scrollX * v.zoom), y: mod(v.scrollY * v.zoom) };
}

/** Dot layer for transform-only panning: `size` is non-null only when it differs from `last` (zoom changed). x and y are in [0, size). */
export function paperLayer(v: PaperView, last: number | null): { size: number | null; x: number; y: number } {
  const d = paperDots(v);
  return { size: d.size === last ? null : d.size, x: d.x, y: d.y };
}

export const ZOOM_MIN = 0.1;
export const ZOOM_MAX = 30;
export const ZOOM_STEP = 1.25;

export function nextZoom(z: number, dir: 1 | -1): number {
  const n = dir === 1 ? z * ZOOM_STEP : z / ZOOM_STEP;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(n * 1000) / 1000));
}

/** Zoom about the viewport centre: screen = (scene + scroll) * zoom, so the centre scene point stays put. */
export function zoomAbout(v: { scrollX: number; scrollY: number; zoom: number; width: number; height: number }, zoom: number) {
  return {
    zoom,
    scrollX: v.scrollX + (v.width / 2) * (1 / zoom - 1 / v.zoom),
    scrollY: v.scrollY + (v.height / 2) * (1 / zoom - 1 / v.zoom),
  };
}

export type RailTool = "pen" | "highlighter" | "eraser" | "select" | "shapes" | "text";
// Flyout order. The Shapes button picks the last chosen one (INK-175, docs/decisions/0075).
export const SHAPES = ["rectangle", "diamond", "ellipse", "arrow", "line"] as const;
export type ShapeTool = (typeof SHAPES)[number];
export const isShape = (t: string): t is ShapeTool => (SHAPES as readonly string[]).includes(t);
export const HIGHLIGHTER = { opacity: 35, strokeWidth: 4 };
export const PEN = { opacity: 100, strokeWidth: 2 };

/** What the rail shows pressed, from an Excalidraw appState subset. null for tools the rail lacks (hand, laser...). */
export function railTool(a: { activeTool: { type: string }; currentItemOpacity: number }): RailTool | null {
  switch (a.activeTool.type) {
    case "freedraw":
      return a.currentItemOpacity < 100 ? "highlighter" : "pen";
    case "eraser":
      return "eraser";
    case "selection":
      return "select";
    case "text":
      return "text";
    case "rectangle":
    case "ellipse":
    case "diamond":
    case "arrow":
    case "line":
      return "shapes";
    default:
      return null;
  }
}

/** Arguments for api.setActiveTool and the appState patch to apply with it, for a tap on a rail tool. */
export function toolTap(tool: RailTool, currentType: string, lastShape: ShapeTool = "rectangle"): { tool: { type: string }; patch: Record<string, number> } {
  if (tool === "pen") {
    return { tool: { type: "freedraw" }, patch: { currentItemOpacity: PEN.opacity, currentItemStrokeWidth: PEN.strokeWidth } };
  }
  if (tool === "highlighter") {
    return {
      tool: { type: "freedraw" },
      patch: { currentItemOpacity: HIGHLIGHTER.opacity, currentItemStrokeWidth: HIGHLIGHTER.strokeWidth },
    };
  }
  // Shapes and text must not inherit the highlighter's 35 percent opacity.
  const solid = { currentItemOpacity: PEN.opacity, currentItemStrokeWidth: PEN.strokeWidth };
  if (tool === "shapes") {
    // A shape already active stays, and keeps the width the user picked.
    return { tool: { type: isShape(currentType) ? currentType : lastShape }, patch: isShape(currentType) ? {} : solid };
  }
  if (tool === "text") return { tool: { type: "text" }, patch: solid };
  return { tool: { type: tool === "select" ? "selection" : tool }, patch: {} };
}

/** A pick from the shapes flyout: the shape, and the solid patch only when coming from a non-shape tool. */
export function pickShape(shape: ShapeTool, currentType: string): { tool: { type: string }; patch: Record<string, number> } {
  return { tool: { type: shape }, patch: isShape(currentType) ? {} : { currentItemOpacity: PEN.opacity, currentItemStrokeWidth: PEN.strokeWidth } };
}

/** Picking an ink colour while the eraser or selection is active switches to the pen. */
export const colourNeedsPen = (type: string) => type === "selection" || type === "eraser" || type === "hand";

/** Which of the three pen colours (token order: charcoal, blue, brick) is current; hex compared case-insensitively. */
export function penIndex(current: string, pens: readonly string[]): number {
  return pens.findIndex((p) => p.toLowerCase() === current.toLowerCase());
}

/** Reads the pen colours from CSS custom properties; `read` is getComputedStyle(root).getPropertyValue in the browser. */
export function penColours(read: (name: string) => string): string[] {
  return ["--color-pen-charcoal", "--color-pen-blue", "--color-pen-brick"].map((n) => read(n).trim());
}

/** Keyboard event init for undo (Ctrl/Cmd+Z) or redo (Shift added). */
export function undoKey(kind: "undo" | "redo", mac: boolean): KeyboardEventInit {
  return {
    key: kind === "redo" ? "Z" : "z",
    code: "KeyZ",
    shiftKey: kind === "redo",
    ctrlKey: !mac,
    metaKey: mac,
    bubbles: true,
    cancelable: true,
  };
}
