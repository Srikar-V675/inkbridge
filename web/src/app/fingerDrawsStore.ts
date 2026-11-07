import { createFingerDraws } from "./fingerDraws";

// The one "Finger draws" setting of this page, shared by the touch router and the fast ink layer (INK-173, INK-181).
function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
export const fingerDraws = createFingerDraws(safeStorage());
