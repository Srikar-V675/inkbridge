// The "Finger draws" setting (INK-173, docs/decisions/0072): off by default, remembered per device.
const KEY = "inkbridge-finger-draws";
type Store = Pick<Storage, "getItem" | "setItem">;
export function loadFingerDraws(s: Store | null): boolean { try { return s?.getItem(KEY) === "1"; } catch { return false; } }
export function saveFingerDraws(s: Store | null, on: boolean): void { try { s?.setItem(KEY, on ? "1" : "0"); } catch { /* blocked: not remembered */ } }
export function createFingerDraws(s: Store | null) {
  let on = loadFingerDraws(s);
  const ls = new Set<() => void>();
  return {
    get: () => on,
    set(v: boolean) { if (v === on) return; on = v; saveFingerDraws(s, v); ls.forEach((l) => l()); },
    subscribe(l: () => void) { ls.add(l); return () => void ls.delete(l); },
  };
}
