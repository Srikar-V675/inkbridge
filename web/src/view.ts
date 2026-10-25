// Per-device memory of where each canvas was last scrolled and zoomed. A viewer convenience, so it
// lives in localStorage (never the server) and every access tolerates a missing or blocked store.

export interface View {
  scrollX: number;
  scrollY: number;
  zoom: number;
}

type Store = Pick<Storage, "getItem" | "setItem">;

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 30;
const key = (canvas: string) => `inkbridge-view-${canvas}`;

export function loadView(storage: Store, canvas: string): View | null {
  try {
    const raw = storage.getItem(key(canvas));
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<View>;
    const { scrollX, scrollY, zoom } = v;
    if (![scrollX, scrollY, zoom].every((n) => typeof n === "number" && Number.isFinite(n))) return null;
    if ((zoom as number) <= 0) return null;
    return {
      scrollX: scrollX as number,
      scrollY: scrollY as number,
      zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom as number)),
    };
  } catch {
    return null;
  }
}

export function saveView(storage: Store, canvas: string, view: View) {
  if (![view.scrollX, view.scrollY, view.zoom].every(Number.isFinite)) return;
  try {
    storage.setItem(key(canvas), JSON.stringify(view));
  } catch {
    // blocked storage: the view simply is not remembered
  }
}
