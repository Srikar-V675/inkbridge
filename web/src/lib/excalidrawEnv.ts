import type { View } from "./view.ts";

type Flags = { EXCALIDRAW_THROTTLE_RENDER?: boolean; EXCALIDRAW_ASSET_PATH?: string };

/** Set the globals Excalidraw reads (INK-101). `base` is Vite's BASE_URL, ending in "/". */
export function configureExcalidraw(win: object, base: string): void {
  const w = win as Flags;
  w.EXCALIDRAW_THROTTLE_RENDER = true; // as excalidraw.com runs it
  w.EXCALIDRAW_ASSET_PATH = `${base}excalidraw-assets/`; // fonts come from our own server, not esm.sh
}

/** Initial appState: pen mode on (the pen draws, fingers pan), plus the remembered view if any. */
export function initialAppState(view: View | null) {
  return {
    penMode: true,
    ...(view && { scrollX: view.scrollX, scrollY: view.scrollY, zoom: { value: view.zoom as never } }),
  };
}
