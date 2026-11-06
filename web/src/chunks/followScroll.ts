import type { View } from "./chunks";

type Api = { onScrollChange(cb: (x: number, y: number, z: { value: number }) => void): () => void };

/** Calls set on every scroll or zoom change, only while active; returns the unsubscribe (INK-174: a hidden overlay costs no React commit per pan frame). */
export function followScroll(api: Api, active: boolean, set: (v: View) => void): () => void {
  if (!active) return () => {};
  return api.onScrollChange((scrollX, scrollY, zoom) => set({ scrollX, scrollY, zoom: zoom.value }));
}
