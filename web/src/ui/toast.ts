export const TOAST_MS = 6000;

/** Call onDismiss after ms; the returned function cancels. */
export function scheduleDismiss(onDismiss: () => void, ms: number = TOAST_MS): () => void {
  const id = setTimeout(onDismiss, ms);
  return () => clearTimeout(id);
}
