// Store behind the properties card (INK-175, docs/decisions/0075), over the Excalidraw API.
// Same pattern as railStore: injected api and env, get() returns the same object until a shown
// field changes. It is hooked on api.onChange, so it must stay cheap: a pointer move reads only
// appState, and the scene is read once after a gesture ends and only when the card can show.
import {
  applyFlag, applyStyle, applyText, layerKey, type LayerKind, controlsFor, sourceFor, stateValue, statePatch, title, unlockAll, valueOf,
  type ControlId, type StyleEl, type ToolDefaults, type Value,
} from "./propsLogic.ts";

export interface PropsSnapshot {
  source: "tool" | "selection" | null;
  title: string;
  controls: ControlId[];
  values: Partial<Record<ControlId, Value>>;
  layers: boolean; // selection actions rows
  anyLocked: boolean; // "Unlock all"
  collapsed: boolean;
}

export interface PropsEnv {
  /** CaptureUpdateAction.NEVER and .IMMEDIATELY, injected so Node tests need not load Excalidraw. */
  never: unknown;
  immediately: unknown;
  mac: boolean;
  container: () => { dispatchEvent(e: Event): boolean } | null;
  makeKey: (init: KeyboardEventInit) => Event;
  nonce: () => number;
  now: () => number;
  measure: (line: string, fontSize: number, fontFamily: number) => number;
  loadFont: (fontFamily: number, fontSize: number) => Promise<void>;
}

export interface PropsState extends Partial<ToolDefaults> {
  activeTool: { type: string };
  selectedElementIds?: Record<string, boolean>;
  editingTextElement?: unknown;
  cursorButton?: string;
  newElement?: unknown;
  selectedElementsAreBeingDragged?: boolean;
  resizingElement?: unknown;
  isRotating?: boolean;
}

export interface PropsApi {
  getAppState(): PropsState;
  getSceneElementsIncludingDeleted(): readonly StyleEl[];
  onChange(cb: (elements: readonly unknown[], appState: PropsState) => void): () => void;
  updateScene(scene: { elements?: readonly StyleEl[]; appState?: Record<string, unknown>; captureUpdate: unknown }): void;
}

const DEFAULTS: (keyof ToolDefaults)[] = [
  "currentItemStrokeColor", "currentItemBackgroundColor", "currentItemFillStyle", "currentItemStrokeWidth",
  "currentItemStrokeStyle", "currentItemRoughness", "currentItemOpacity", "currentItemRoundness",
  "currentItemStartArrowhead", "currentItemEndArrowhead", "currentItemArrowType", "currentItemFontFamily",
  "currentItemFontSize", "currentItemTextAlign",
];

const inGesture = (a: PropsState) =>
  a.cursorButton === "down" || a.newElement != null || Boolean(a.selectedElementsAreBeingDragged) ||
  a.resizingElement != null || Boolean(a.isRotating);

/** What the card reads from appState; compared elementwise, so a pointer move costs a handful of comparisons. */
const keyOf = (a: PropsState): unknown[] => [
  a.selectedElementIds, a.activeTool.type, a.editingTextElement != null, ...DEFAULTS.map((k) => a[k]),
];
const sameKey = (x: unknown[], y: unknown[]) => x.length === y.length && x.every((v, i) => v === y[i]);

const shallow = (a: object, b: object) => {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => (a as never)[k] === (b as never)[k]);
};
const sameSnap = (a: PropsSnapshot, b: PropsSnapshot) =>
  a.source === b.source && a.title === b.title && a.layers === b.layers && a.anyLocked === b.anyLocked &&
  a.collapsed === b.collapsed && a.controls.length === b.controls.length &&
  a.controls.every((c, i) => c === b.controls[i]) && shallow(a.values, b.values);

const selectedIds = (a: PropsState): Set<string> => {
  const ids = new Set<string>();
  for (const k in a.selectedElementIds) if (a.selectedElementIds[k]) ids.add(k);
  return ids;
};

export function createPropsStore(api: PropsApi, env: PropsEnv) {
  const listeners = new Set<() => void>();
  let collapsed = false;
  let lastKey: unknown[] = [];
  let lastElements: readonly unknown[] | null = null;

  const hidden = (): PropsSnapshot => ({ source: null, title: "", controls: [], values: {}, layers: false, anyLocked: false, collapsed });

  const build = (): PropsSnapshot => {
    const a = api.getAppState();
    lastKey = keyOf(a);
    const ids = selectedIds(a);
    let scene: readonly StyleEl[] = [];
    let selected: StyleEl[] = [];
    if (ids.size) {
      scene = api.getSceneElementsIncludingDeleted();
      selected = scene.filter((e) => ids.has(e.id) && !e.isDeleted);
    }
    const { source, types } = sourceFor(a, selected);
    if (!source) return hidden();
    if (!ids.size) scene = api.getSceneElementsIncludingDeleted();
    const controls = controlsFor(types);
    const values: Partial<Record<ControlId, Value>> = {};
    for (const c of controls) values[c] = source === "selection" ? valueOf(c, selected) : stateValue(c, a);
    let anyLocked = false;
    for (let i = 0; i < scene.length; i++) {
      if (scene[i].locked && !scene[i].isDeleted) {
        anyLocked = true;
        break;
      }
    }
    return { source, title: title(source, types, selected.length), controls, values, layers: source === "selection", anyLocked, collapsed };
  };

  let snap = build();
  const refresh = () => {
    const n = build();
    if (sameSnap(n, snap)) return;
    snap = n;
    listeners.forEach((l) => l());
  };

  const offChange = api.onChange((elements, a) => {
    if (inGesture(a)) return; // a stroke, drag, resize or finger-down: nothing is read, nothing notified
    const k = keyOf(a);
    if (sameKey(k, lastKey) && (elements === lastElements || snap.source !== "selection")) {
      lastElements = elements;
      return;
    }
    lastElements = elements;
    refresh();
  });

  // Layers, duplicate and delete rebuild indexes, groups, bound text and arrows: Excalidraw's action manager
  // does it, so the card sends the action's own shortcut to the canvas (the rail does the same for undo).
  const key = (kind: LayerKind) => void env.container()?.dispatchEvent(env.makeKey(layerKey(kind, env.mac)));

  const toolOnly = (a: PropsState) => snap.source !== "selection" || a.editingTextElement != null;

  return {
    get: () => snap,
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    /** Fonts load first, so the call may return a promise; the UI ignores it. */
    set(control: ControlId, value: Value): void | Promise<void> {
      const a = api.getAppState();
      if (!toolOnly(a) && (control === "fontFamily" || control === "fontSize") && typeof value === "number") {
        const text = () => api.getSceneElementsIncludingDeleted();
        const write = () => {
          const scene = text();
          const next = applyText(scene, selectedIds(api.getAppState()), control, value, env, env.measure);
          if (next !== scene) api.updateScene({ elements: next, captureUpdate: env.immediately });
          refresh();
        };
        if (control === "fontSize") return write();
        const ids = selectedIds(a);
        const first = text().find((e) => ids.has(e.id) && !e.isDeleted && e.type === "text");
        return env.loadFont(value, first?.fontSize ?? 20).then(write);
      }
      if (toolOnly(a)) {
        api.updateScene({ appState: statePatch(control, value), captureUpdate: env.never });
      } else {
        const scene = api.getSceneElementsIncludingDeleted();
        const next = applyStyle(scene, selectedIds(a), control, value, env);
        if (next !== scene) api.updateScene({ elements: next, captureUpdate: env.immediately });
      }
      refresh();
    },
    layer: (kind: Exclude<LayerKind, "duplicate" | "delete">) => key(kind),
    duplicate: () => key("duplicate"),
    remove: () => key("delete"),
    toggleCollapsed() {
      collapsed = !collapsed;
      refresh();
    },
    lock() {
      const a = api.getAppState();
      const scene = api.getSceneElementsIncludingDeleted();
      const next = applyFlag(scene, selectedIds(a), { locked: true }, env);
      if (next !== scene) api.updateScene({ elements: next, appState: { selectedElementIds: {} }, captureUpdate: env.immediately });
      refresh();
    },
    unlockAll() {
      const scene = api.getSceneElementsIncludingDeleted();
      const next = unlockAll(scene, env);
      if (next !== scene) api.updateScene({ elements: next, captureUpdate: env.immediately });
      refresh();
    },
    dispose: offChange,
  };
}
