// Pure logic for the properties card (INK-175, docs/decisions/0075): which rows an element kind
// supports, how a row's value is read, and the style patches written back. No React, DOM or
// Excalidraw imports, so the Node test runner can load it.

export type ElType = "rectangle" | "diamond" | "ellipse" | "line" | "arrow" | "freedraw" | "text" | "image" | "other";
export type ControlId =
  | "stroke" | "background" | "fill" | "width" | "style" | "sloppiness" | "edges" | "opacity"
  | "arrowStart" | "arrowEnd" | "arrowType" | "fontFamily" | "fontSize" | "textAlign";
export type Value = string | number | "mixed" | null;

export const typeOf = (t: string): ElType =>
  (["rectangle", "diamond", "ellipse", "line", "arrow", "freedraw", "text", "image"] as const).find((x) => x === t) ?? "other";

const CLOSED: ElType[] = ["rectangle", "diamond", "ellipse"];
const STROKED: ElType[] = [...CLOSED, "line", "arrow"];
export const SUPPORT: Record<ControlId, readonly ElType[]> = {
  stroke: [...STROKED, "freedraw", "text"],
  background: CLOSED, fill: CLOSED,
  width: [...STROKED, "freedraw"],
  style: STROKED, sloppiness: STROKED,
  edges: ["rectangle", "diamond", "line"],
  opacity: ["rectangle", "diamond", "ellipse", "line", "arrow", "freedraw", "text", "image", "other"],
  arrowStart: ["arrow"], arrowEnd: ["arrow"], arrowType: ["arrow"],
  fontFamily: ["text"], fontSize: ["text"], textAlign: ["text"],
};
export const ORDER = Object.keys(SUPPORT) as ControlId[]; // display order

/** The controls every one of `types` supports, in display order; [] for an empty list. */
export const controlsFor = (types: readonly ElType[]): ControlId[] =>
  types.length === 0 ? [] : ORDER.filter((c) => types.every((t) => SUPPORT[c].includes(t)));

// Option tables shared by the UI and the patches. Font numbers are Excalidraw 0.18's FONT_FAMILY
// Excalifont (5), Nunito (6) and Cascadia (3); a test pins them, this file imports nothing from Excalidraw.
export const WIDTHS: readonly (readonly [string, number])[] = [["thin", 1], ["bold", 2], ["extra bold", 4]];
export const STYLES = ["solid", "dashed", "dotted"] as const;
export const FILLS = ["hachure", "cross-hatch", "solid"] as const;
export const SLOPPINESS: readonly (readonly [string, number])[] = [["architect", 0], ["artist", 1], ["cartoonist", 2]];
export const EDGES = ["sharp", "round"] as const;
export const HEADS = ["none", "arrow", "triangle", "bar", "dot"] as const;
export const ARROW_TYPES = ["sharp", "round", "elbow"] as const;
export const FONTS: readonly (readonly [string, number])[] = [["Hand", 5], ["Normal", 6], ["Code", 3]];
export const SIZES: readonly (readonly [string, number])[] = [["S", 16], ["M", 20], ["L", 28], ["XL", 36]];
// Excalidraw 0.18 font metrics `lineHeight` per family (getLineHeight): Excalifont, Nunito, Cascadia.
export const LINE_HEIGHT: Record<number, number> = { 5: 1.25, 6: 1.35, 3: 1.2 };
export const ALIGNS = ["left", "center", "right"] as const;

export const PALETTE_TOKENS = {
  stroke: ["--color-pen-charcoal", "--color-pen-blue", "--color-pen-brick", "--color-soft-ink", "--color-dot"],
  background: ["--color-dot", "--color-soft-ink", "--color-pen-blue", "--color-pen-brick"],
};

/** Colours for the swatches; `read` is getComputedStyle(root).getPropertyValue in the browser. */
export function palette(read: (name: string) => string): { stroke: string[]; background: string[] } {
  return {
    stroke: PALETTE_TOKENS.stroke.map((n) => read(n).trim()),
    background: ["transparent", ...PALETTE_TOKENS.background.map((n) => read(n).trim())],
  };
}

export interface StyleEl {
  id: string;
  type: string;
  version: number;
  isDeleted?: boolean;
  locked?: boolean;
  customData?: { draft?: boolean } | null;
  strokeColor?: string;
  backgroundColor?: string;
  fillStyle?: string;
  strokeWidth?: number;
  strokeStyle?: string;
  roughness?: number;
  opacity?: number;
  roundness?: unknown;
  startArrowhead?: string | null;
  endArrowhead?: string | null;
  elbowed?: boolean;
  fontFamily?: number;
  fontSize?: number;
  textAlign?: string;
  [k: string]: unknown;
}

const READ: Record<ControlId, (e: StyleEl) => Value> = {
  stroke: (e) => (e.strokeColor ?? "").toLowerCase(),
  background: (e) => (e.backgroundColor ?? "").toLowerCase(),
  fill: (e) => e.fillStyle ?? null,
  width: (e) => e.strokeWidth ?? null,
  style: (e) => e.strokeStyle ?? null,
  sloppiness: (e) => e.roughness ?? null,
  edges: (e) => (e.roundness ? "round" : "sharp"),
  opacity: (e) => e.opacity ?? null,
  arrowStart: (e) => e.startArrowhead ?? "none",
  arrowEnd: (e) => e.endArrowhead ?? "none",
  arrowType: (e) => (e.elbowed ? "elbow" : e.roundness ? "round" : "sharp"),
  fontFamily: (e) => e.fontFamily ?? null,
  fontSize: (e) => e.fontSize ?? null,
  textAlign: (e) => e.textAlign ?? null,
};

/** The shared value of a control over `els`, "mixed" when they differ, null for an empty list. */
export function valueOf(control: ControlId, els: readonly StyleEl[]): Value {
  if (els.length === 0) return null;
  const first = READ[control](els[0]);
  return els.every((e) => READ[control](e) === first) ? first : "mixed";
}

export interface ToolDefaults {
  currentItemStrokeColor: string;
  currentItemBackgroundColor: string;
  currentItemFillStyle: string;
  currentItemStrokeWidth: number;
  currentItemStrokeStyle: string;
  currentItemRoughness: number;
  currentItemOpacity: number;
  currentItemRoundness: string;
  currentItemStartArrowhead: string | null;
  currentItemEndArrowhead: string | null;
  currentItemArrowType: string;
  currentItemFontFamily: number;
  currentItemFontSize: number;
  currentItemTextAlign: string;
}

const STATE_KEY: Record<ControlId, keyof ToolDefaults> = {
  stroke: "currentItemStrokeColor", background: "currentItemBackgroundColor", fill: "currentItemFillStyle",
  width: "currentItemStrokeWidth", style: "currentItemStrokeStyle", sloppiness: "currentItemRoughness",
  edges: "currentItemRoundness", opacity: "currentItemOpacity", arrowStart: "currentItemStartArrowhead",
  arrowEnd: "currentItemEndArrowhead", arrowType: "currentItemArrowType", fontFamily: "currentItemFontFamily",
  fontSize: "currentItemFontSize", textAlign: "currentItemTextAlign",
};

/** The same table read from the tool defaults (appState.currentItem*). */
export function stateValue(control: ControlId, a: Partial<ToolDefaults>): Value {
  const v = a[STATE_KEY[control]];
  if (control === "arrowStart" || control === "arrowEnd") return v ?? "none";
  if ((control === "stroke" || control === "background") && typeof v === "string") return v.toLowerCase();
  return v ?? null;
}

/** appState patch that sets a tool default. */
export function statePatch(control: ControlId, value: Value): Record<string, unknown> {
  const v = (control === "arrowStart" || control === "arrowEnd") && value === "none" ? null : value;
  return { [STATE_KEY[control]]: v };
}

/** Keys a patch may write. Geometry only comes from fitText; points, pressures, simulatePressure never. */
export const PATCH_KEYS: ReadonlySet<string> = new Set([
  "strokeColor", "backgroundColor", "fillStyle", "strokeWidth", "strokeStyle", "roughness", "opacity", "roundness",
  "startArrowhead", "endArrowhead", "elbowed", "fontFamily", "fontSize", "textAlign", "locked", "lineHeight",
]);

/** Patch for one element, or null when the control does not apply to it. */
export function elementPatch(control: ControlId, value: Value, el: StyleEl): Record<string, unknown> | null {
  const round = () => ({ type: el.type === "line" || el.type === "arrow" ? 2 : 3 }); // 2 proportional, 3 adaptive (Excalidraw ROUNDNESS)
  switch (control) {
    case "stroke": return { strokeColor: value };
    case "background": return { backgroundColor: value };
    case "fill": return { fillStyle: value };
    case "width": return { strokeWidth: value };
    case "style": return { strokeStyle: value };
    case "sloppiness": return { roughness: value };
    case "opacity": return { opacity: value };
    case "edges": return { roundness: value === "round" ? round() : null };
    case "arrowStart": return { startArrowhead: value === "none" ? null : value };
    case "arrowEnd": return { endArrowhead: value === "none" ? null : value };
    case "arrowType":
      if (el.elbowed || value === "elbow") return null; // elbow routing is Excalidraw's: tool default only
      return { elbowed: false, roundness: value === "round" ? round() : null };
    case "fontFamily": return { fontFamily: value };
    case "fontSize": return { fontSize: value };
    case "textAlign": return { textAlign: value };
  }
}

const same = (a: unknown, b: unknown) => a === b || (typeof a === "object" && a !== null && JSON.stringify(a) === JSON.stringify(b));

export interface RestyleEnv { nonce: () => number; now: () => number }

export function restyle<T extends { version: number }>(el: T, patch: Record<string, unknown>, env: RestyleEnv): T {
  if (Object.entries(patch).every(([k, v]) => same((el as unknown as Record<string, unknown>)[k], v))) return el; // nothing changed: same object
  // Same id, higher version: sceneSync sends any element whose version differs. Spreading keeps points, pressures, simulatePressure.
  return { ...el, ...patch, version: el.version + 1, versionNonce: env.nonce(), updated: env.now() };
}

const editable = (e: StyleEl, ids: ReadonlySet<string>) => ids.has(e.id) && !e.isDeleted && !e.customData?.draft;

/** Applies a control to the selected, live, non-draft elements that support it; returns `scene` itself if nothing changed. */
export function applyStyle(
  scene: readonly StyleEl[], ids: ReadonlySet<string>, control: ControlId, value: Value, env: RestyleEnv,
): StyleEl[] {
  let changed = false;
  const out = scene.map((e) => {
    if (!editable(e, ids) || !SUPPORT[control].includes(typeOf(e.type))) return e;
    const patch = elementPatch(control, value, e);
    if (!patch) return e;
    const next = restyle(e, patch, env);
    if (next !== e) changed = true;
    return next;
  });
  return changed ? out : (scene as StyleEl[]);
}

/** Lock or unlock the selected, live, non-draft elements. */
export function applyFlag(
  scene: readonly StyleEl[], ids: ReadonlySet<string>, flag: { locked: boolean }, env: RestyleEnv,
): StyleEl[] {
  let changed = false;
  const out = scene.map((e) => {
    if (!editable(e, ids)) return e;
    const next = restyle(e, flag, env);
    if (next !== e) changed = true;
    return next;
  });
  return changed ? out : (scene as StyleEl[]);
}

/** Unlocks every live locked element: they cannot be selected, so this ignores the selection. */
export function unlockAll(scene: readonly StyleEl[], env: RestyleEnv): StyleEl[] {
  let changed = false;
  const out = scene.map((e) => {
    if (e.isDeleted || !e.locked || e.customData?.draft) return e;
    changed = true;
    return restyle(e, { locked: false }, env);
  });
  return changed ? out : (scene as StyleEl[]);
}

export interface TextBox { x: number; y: number; width: number; height: number; text: string; lineHeight: number; containerId?: unknown; autoResize?: boolean }

/** New box for a text element after a size or font change, grown about its centre; null for bound or fixed-width text. */
export function fitText(
  el: TextBox, next: { fontSize: number; fontFamily: number },
  measure: (line: string, fontSize: number, fontFamily: number) => number,
): { x: number; y: number; width: number; height: number } | null {
  if (el.containerId || el.autoResize === false) return null;
  const lines = el.text.split("\n");
  const width = Math.max(...lines.map((l) => measure(l, next.fontSize, next.fontFamily)));
  const height = lines.length * next.fontSize * el.lineHeight;
  return { x: el.x + (el.width - width) / 2, y: el.y + (el.height - height) / 2, width, height };
}

/** Font family or size on the selected live, non-draft text: the style patch plus the re-measured box. */
export function applyText(
  scene: readonly StyleEl[], ids: ReadonlySet<string>, control: "fontFamily" | "fontSize", value: number, env: RestyleEnv,
  measure: (line: string, fontSize: number, fontFamily: number) => number,
): StyleEl[] {
  let changed = false;
  const out = scene.map((e) => {
    if (!editable(e, ids) || e.type !== "text") return e;
    const patch = elementPatch(control, value, e);
    if (!patch || Object.entries(patch).every(([k, v]) => e[k] === v)) return e;
    const next = {
      fontSize: control === "fontSize" ? value : (e.fontSize ?? 20),
      fontFamily: control === "fontFamily" ? value : (e.fontFamily ?? 5),
    };
    // A new family brings its own line height (as Excalidraw does); bound or fixed-width text keeps its box and lineHeight.
    const lineHeight = control === "fontFamily" ? (LINE_HEIGHT[value] ?? (e.lineHeight as number)) : (e.lineHeight as number);
    const box = fitText({ ...(e as unknown as TextBox), lineHeight }, next, measure);
    changed = true;
    return restyle(e, { ...patch, ...(box ? { ...box, lineHeight } : {}) }, env);
  });
  return changed ? out : (scene as StyleEl[]);
}

const TOOL_TYPES = ["rectangle", "diamond", "ellipse", "arrow", "line", "text", "freedraw"];

export type CardTool = "pen" | "highlighter" | "shapes" | "text";
export const OPEN_DEFAULT: Record<CardTool, boolean> = { pen: false, highlighter: false, shapes: true, text: true };
const SHAPE_TYPES = ["rectangle", "diamond", "ellipse", "arrow", "line"];

/** Which per-tool open state the active tool uses; null for tools with no card. `kind` says pen or highlighter. */
export function cardTool(a: { activeTool: { type: string } }, kind: "pen" | "highlighter"): CardTool | null {
  const t = a.activeTool.type;
  if (t === "freedraw") return kind;
  if (SHAPE_TYPES.includes(t)) return "shapes";
  return t === "text" ? "text" : null;
}

/** What the card edits: the selection, the tool defaults, or nothing (hidden). Drafts are the agent's: never shown. */
export function sourceFor(
  a: { activeTool: { type: string } }, selected: readonly StyleEl[], open = true,
): { source: "selection" | "tool" | null; types: ElType[] } {
  if (selected.some((e) => e.customData?.draft)) return { source: null, types: [] };
  if (selected.length) return { source: "selection", types: [...new Set(selected.map((e) => typeOf(e.type)))] };
  if (open && TOOL_TYPES.includes(a.activeTool.type)) return { source: "tool", types: [typeOf(a.activeTool.type)] };
  return { source: null, types: [] };
}

const LABEL: Record<ElType, string> = {
  rectangle: "Rectangle", diamond: "Diamond", ellipse: "Ellipse", line: "Line", arrow: "Arrow",
  freedraw: "Freedraw", text: "Text", image: "Image", other: "Element",
};

export function title(source: "selection" | "tool", types: readonly ElType[], count: number): string {
  if (source === "selection" && count > 1) return `${count} selected`;
  const t = LABEL[types[0] ?? "other"];
  return source === "tool" ? `${t} tool` : t;
}

export type LayerKind = "back" | "backward" | "forward" | "front" | "duplicate" | "delete";

/** Keyboard shortcut of an Excalidraw 0.18 action, dispatched on the canvas (the action manager does the work). */
export function layerKey(kind: LayerKind, mac: boolean): KeyboardEventInit {
  const mod = mac ? { metaKey: true } : { ctrlKey: true };
  const o = { bubbles: true, cancelable: true };
  switch (kind) {
    case "backward": return { key: "[", code: "BracketLeft", ...mod, ...o };
    case "forward": return { key: "]", code: "BracketRight", ...mod, ...o };
    case "back":
    case "front": {
      const left = kind === "back";
      const code = left ? "BracketLeft" : "BracketRight";
      return mac
        ? { code, key: left ? "[" : "]", metaKey: true, altKey: true, ...o }
        : { code, key: left ? "{" : "}", ctrlKey: true, shiftKey: true, ...o };
    }
    case "duplicate": return { key: "d", code: "KeyD", ...mod, ...o };
    case "delete": return { key: "Delete", code: "Delete", ...o };
  }
}
