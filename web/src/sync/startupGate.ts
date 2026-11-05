// Runs deferred startup work once the canvas has painted its scene (INK-080). open() is idempotent.
export function createStartupGate(
  defer: (f: () => void) => void = (f) =>
    typeof requestIdleCallback === "function"
      ? void requestIdleCallback(f, { timeout: 1500 })
      : void setTimeout(f, 0),
) {
  let opened = false;
  const waiting: Array<() => void> = [];
  return {
    open() {
      if (opened) return;
      opened = true;
      defer(() => waiting.splice(0).forEach((f) => f()));
    },
    /** Returns a cancel function. Work queued after open still goes through defer once. */
    whenReady(f: () => void): () => void {
      let live = true;
      if (opened) {
        defer(() => live && f());
      } else {
        waiting.push(() => live && f());
      }
      return () => {
        live = false;
      };
    },
  };
}
