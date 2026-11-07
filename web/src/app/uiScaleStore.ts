import { createUiScale } from "./uiScale";

// The one UI-size setting of this page (INK-177). The URL is read once at load, so in-app canvas switches keep the value.
function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
const coarse = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
export const uiScale = createUiScale(safeStorage(), { coarse, search: window.location.search });
