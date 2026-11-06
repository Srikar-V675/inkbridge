/** True when every ref is identical to the previous call's. A cheap guard for onChange subscribers: a pan frame passes the same elements array and selection object (INK-174, decision 0073). */
export function createGate() {
  let last: readonly unknown[] | null = null;
  return (...refs: unknown[]): boolean => {
    if (last && last.length === refs.length && refs.every((r, i) => r === last![i])) return true;
    last = refs;
    return false;
  };
}
