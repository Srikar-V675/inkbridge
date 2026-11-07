// The "UI size" setting (INK-177, docs/decisions/0083): one scale for the shell chrome, remembered per device.
export const UI_KEY = "inkbridge-ui-scale";
export const UI_MIN = 0.6;
export const UI_MAX = 1.2;
export const UI_SIZES = [
  { label: "Small", short: "S", scale: 0.8 },
  { label: "Medium", short: "M", scale: 0.9 },
  { label: "Large", short: "L", scale: 1 },
] as const;
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export const defaultScale = (coarse: boolean): number => (coarse ? 0.8 : 1);
export const validScale = (n: number): boolean => Number.isFinite(n) && n >= UI_MIN && n <= UI_MAX;

/** `?ui=0.7` gives 0.7, `?ui=0` gives "clear" (forget the saved value), anything else gives null. */
export function parseUiParam(search: string): number | "clear" | null {
  const raw = new URLSearchParams(search).get("ui");
  if (raw === null || raw.trim() === "") return null;
  const n = Number(raw);
  if (n === 0) return "clear";
  return validScale(n) ? n : null;
}

export function loadUiScale(s: Store | null, coarse: boolean): number {
  try {
    const raw = s?.getItem(UI_KEY);
    if (raw != null && raw !== "") {
      const n = Number(raw);
      if (validScale(n)) return n;
    }
  } catch {
    /* blocked: use the default */
  }
  return defaultScale(coarse);
}

export function saveUiScale(s: Store | null, n: number): void {
  try {
    s?.setItem(UI_KEY, String(n));
  } catch {
    /* blocked: not remembered */
  }
}

/** The next larger preset, wrapping from Large (or anything above the presets) to Small. */
export function nextSize(scale: number): number {
  const hit = UI_SIZES.find((p) => p.scale > scale + 1e-9);
  return hit ? hit.scale : UI_SIZES[0].scale;
}

export function sizeLabel(scale: number): string {
  return UI_SIZES.find((p) => Math.abs(p.scale - scale) < 1e-9)?.label ?? String(scale);
}

export function sizeShort(scale: number): string {
  return UI_SIZES.find((p) => Math.abs(p.scale - scale) < 1e-9)?.short ?? String(scale);
}

export function createUiScale(s: Store | null, o: { coarse: boolean; search: string }) {
  const param = parseUiParam(o.search);
  let scale: number;
  if (typeof param === "number") {
    scale = param;
    saveUiScale(s, scale); // remembered on use, like ?devicelog
  } else if (param === "clear") {
    try {
      s?.removeItem(UI_KEY);
    } catch {
      /* blocked: nothing to clear */
    }
    scale = defaultScale(o.coarse);
  } else {
    scale = loadUiScale(s, o.coarse);
  }
  const ls = new Set<() => void>();
  const api = {
    get: () => scale,
    set(n: number) {
      if (!validScale(n) || n === scale) return;
      scale = n;
      saveUiScale(s, n);
      ls.forEach((l) => l());
    },
    cycle() {
      api.set(nextSize(scale));
    },
    subscribe(l: () => void) {
      ls.add(l);
      return () => void ls.delete(l);
    },
  };
  return api;
}
