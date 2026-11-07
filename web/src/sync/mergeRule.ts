export interface Stamped {
  version?: number;
  versionNonce?: number;
}
const n = (v: number | undefined) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
/** Same rule as server `elements.wins` (decision 0038, 0080): higher version, then lower nonce; equal keeps the current. */
export const winsOver = (incoming: Stamped, current: Stamped): boolean =>
  n(incoming.version) > n(current.version) ||
  (n(incoming.version) === n(current.version) && n(incoming.versionNonce) < n(current.versionNonce));
