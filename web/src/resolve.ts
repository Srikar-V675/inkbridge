// Accept / Reject / Accept all for agent drafts (INK-045), framework-free so Node can test it.
// Both helpers match by the op's server-issued id prefix, never by customData alone: customData
// is client-writable and user ink must never be matched.

import type { DraftElement } from "./drafts.ts";

/** Accept: make the op's elements ordinary content (no draft tag, solid, text back to full). */
export function acceptOp<T extends DraftElement>(els: readonly T[], prefix: string): T[] {
  return els.map((e) => {
    if (!e.id.startsWith(prefix) || e.isDeleted) return e;
    const { draft: _draft, ...cd } = (e.customData ?? {}) as Record<string, unknown>;
    return {
      ...e,
      customData: cd,
      strokeStyle: "solid",
      opacity: e.type === "text" ? 100 : e.opacity,
      version: (e.version ?? 0) + 1,
    };
  });
}

/** Ops that still have live draft elements in the scene, in scene order. */
export function draftOps(els: readonly DraftElement[]): { opId: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const e of els) {
    if (e.isDeleted || !e.customData?.draft) continue;
    const opId = e.customData.op_id;
    if (typeof opId !== "string" || !e.id.startsWith(`${opId}:`)) continue;
    counts.set(opId, (counts.get(opId) ?? 0) + 1);
  }
  return [...counts].map(([opId, count]) => ({ opId, count }));
}
