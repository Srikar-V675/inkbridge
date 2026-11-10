// The placed-op list and the pure function from it to the scene's draft elements (INK-115,
// decision 0090). The server owns placement; the scene shows exactly the placed ops.
import { draftBox, isFlowArrow } from "./draftView.ts";
import { draftOpId, isDraftTagged, markDraft, type DraftElement } from "./drafts.ts";

export interface PlacedOp {
  id: string;
  payload: { id_prefix: string; anchor_resolved?: string | null; question_id?: string | null };
  elements: DraftElement[];
  box: { x: number; y: number; width: number; height: number };
}

export function createDraftStore() {
  let ops: PlacedOp[] = [];
  const subs = new Set<() => void>();
  const emit = () => subs.forEach((cb) => cb());
  return {
    ids: () => ops.map((o) => o.id),
    get: (id: string) => ops.find((o) => o.id === id),
    /** A stable reference until the next change (useSyncExternalStore). */
    list: () => ops,
    set(next: PlacedOp[]) {
      ops = next;
      emit();
    },
    upsert(op: PlacedOp) {
      ops = ops.some((o) => o.id === op.id) ? ops.map((o) => (o.id === op.id ? op : o)) : [...ops, op];
      emit();
    },
    remove(id: string) {
      if (!ops.some((o) => o.id === id)) return;
      ops = ops.filter((o) => o.id !== id);
      emit();
    },
    subscribe(cb: () => void) {
      subs.add(cb);
      return () => void subs.delete(cb);
    },
  };
}
export type DraftStore = ReturnType<typeof createDraftStore>;

/**
 * Scene = user ink + the draft elements of the placed ops. Adds missing ones (once), removes live
 * drafts whose op is gone. Matching goes through `draftOpId` (the id-prefix rule), so a user
 * element with a forged tag is never removed. Returns the same array when nothing changed.
 */
export function reconcile<T extends DraftElement>(scene: readonly T[], ops: readonly PlacedOp[]): T[] {
  const live = new Set(ops.map((o) => o.id));
  const prefixes = ops.map((o) => o.payload.id_prefix);
  const kept = scene.filter((e) => {
    const id = draftOpId(e);
    // A solid element the server deleted (unaccept) under a placed op's prefix makes room for its draft again.
    if (id === null) return !(e.isDeleted && !isDraftTagged(e) && prefixes.some((p) => e.id.startsWith(p)));
    return live.has(id);
  });
  const have = new Set(kept.map((e) => e.id)); // an erased draft counts: the user erased it, so it stays gone
  const add = ops.flatMap((o) =>
    markDraft(o.elements.filter((e) => e.id.startsWith(o.payload.id_prefix) && !have.has(e.id)), o.id),
  );
  return add.length || kept.length !== scene.length ? [...kept, ...(add as T[])] : (scene as T[]);
}

/** How far the user dragged the draft: its bbox origin minus the placed box origin. */
export function offsetOf(scene: readonly DraftElement[], op: PlacedOp): { dx: number; dy: number } {
  const box = draftBox(scene.filter((e) => draftOpId(e) === op.id && !isFlowArrow(e)), op.id);
  if (!box) return { dx: 0, dy: 0 };
  const r = (n: number) => Math.round(n * 100) / 100 || 0;
  return { dx: r(box.x - op.box.x), dy: r(box.y - op.box.y) };
}

/** A reload's elements (saved scene, no drafts) keep the draft elements already on the canvas, so a dragged or erased draft stays as it is. */
export function reloadWithDrafts<T extends DraftElement>(next: readonly T[], current: readonly T[], ops: readonly PlacedOp[]): T[] {
  return reconcile([...next, ...current.filter(isDraftTagged)], ops);
}
