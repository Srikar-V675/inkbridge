// Pure helpers that turn an agent op into draft elements (tech ref 9.9). No Excalidraw import, so
// they run under Node's test runner; App.tsx supplies the Excalidraw/Mermaid conversion.
//
// Rules: drafts only ever ADD elements. Every element an op creates gets an id starting with the
// op's server-issued `id_prefix` (the server refuses any other id in the ack, decision 0009), is
// tagged customData {author:"agent", draft:true, op_id} and drawn dashed. User elements are never
// touched; Reject removes exactly the elements carrying the op's prefix.

export interface Placement {
  x: number;
  y: number;
}

export interface PendingOp {
  op_id: string;
  op_type: "write_text" | "draw_diagram";
  payload: {
    text?: string;
    mermaid?: string;
    anchor?: string;
    placement: Placement;
    id_prefix: string;
  };
}

export interface DraftElement {
  id: string;
  version?: number;
  x: number;
  y: number;
  width?: number;
  height?: number;
  points?: readonly (readonly number[])[];
  containerId?: string | null;
  frameId?: string | null;
  groupIds?: readonly string[];
  boundElements?: readonly { id: string; type: string }[] | null;
  startBinding?: { elementId: string; [k: string]: unknown } | null;
  endBinding?: { elementId: string; [k: string]: unknown } | null;
  customData?: Record<string, unknown>;
  isDeleted?: boolean;
  [key: string]: unknown;
}

/** Elements already drawn for this op (a replayed op must not be drawn twice). */
export function opElements<T extends DraftElement>(elements: readonly T[], prefix: string): T[] {
  return elements.filter((e) => e.id.startsWith(prefix));
}

/**
 * Give every new element an id `<prefix><n>` and rewrite every reference between them
 * (bound text, container's boundElements, arrow bindings, frames). References to ids outside the
 * set are dropped: a draft must never point at user ink.
 */
export function prefixIds<T extends DraftElement>(elements: readonly T[], prefix: string): T[] {
  const map = new Map(elements.map((e, i) => [e.id, `${prefix}${i + 1}`]));
  // Groups get op-scoped ids too, so a draft can never join one of the user's groups.
  const groups = new Map<string, string>();
  const group = (g: string) => {
    if (!groups.has(g)) groups.set(g, `${prefix}g${groups.size + 1}`);
    return groups.get(g)!;
  };
  const ref = (id: string | null | undefined) => (id != null ? (map.get(id) ?? null) : id);
  const binding = <B extends { elementId: string } | null | undefined>(b: B): B | null => {
    if (!b) return b ?? null;
    const id = map.get(b.elementId);
    return id ? ({ ...b, elementId: id } as B) : null;
  };
  return elements.map((e) => {
    const out: T = { ...e, id: map.get(e.id)! };
    if ("containerId" in e) out.containerId = ref(e.containerId);
    if ("frameId" in e) out.frameId = ref(e.frameId);
    if (e.boundElements)
      out.boundElements = e.boundElements
        .filter((b) => map.has(b.id))
        .map((b) => ({ ...b, id: map.get(b.id)! }));
    if (e.groupIds) out.groupIds = e.groupIds.map(group);
    if ("startBinding" in e) out.startBinding = binding(e.startBinding);
    if ("endBinding" in e) out.endBinding = binding(e.endBinding);
    return out;
  });
}

function bounds(elements: readonly DraftElement[]) {
  let minX = Infinity;
  let minY = Infinity;
  for (const e of elements) {
    if (e.points?.length) {
      minX = Math.min(minX, e.x + Math.min(...e.points.map((p) => p[0])));
      minY = Math.min(minY, e.y + Math.min(...e.points.map((p) => p[1])));
    } else {
      minX = Math.min(minX, e.x);
      minY = Math.min(minY, e.y);
    }
  }
  return { minX, minY };
}

/** Move the group so its top-left corner sits at the server's placement. */
export function placeAt<T extends DraftElement>(elements: readonly T[], at: Placement): T[] {
  if (!elements.length) return [];
  const { minX, minY } = bounds(elements);
  const dx = at.x - minX;
  const dy = at.y - minY;
  return elements.map((e) => ({ ...e, x: e.x + dx, y: e.y + dy }));
}

/** Tag as an agent draft of this op and draw it dashed (and a little faded, for text). */
export function markDraft<T extends DraftElement>(elements: readonly T[], opId: string): T[] {
  return elements.map((e) => ({
    ...e,
    strokeStyle: "dashed",
    opacity: e.type === "text" ? 70 : (e.opacity ?? 100),
    customData: { ...(e.customData ?? {}), author: "agent", draft: true, op_id: opId },
  }));
}

/** The whole pipeline after conversion: fresh prefixed ids, placed, tagged. */
export function toDrafts<T extends DraftElement>(converted: readonly T[], op: PendingOp): T[] {
  return markDraft(
    placeAt(prefixIds(converted, op.payload.id_prefix), op.payload.placement),
    op.op_id,
  );
}

/**
 * Reject: delete every element carrying the op's prefix (a sweep, so it also catches elements the
 * ack did not list), and nothing else. Deletion is Excalidraw's soft delete with a version bump so
 * autosave and the conflict merge keep it.
 */
export function rejectOp<T extends DraftElement>(elements: readonly T[], prefix: string): T[] {
  return elements.map((e) =>
    e.id.startsWith(prefix) && !e.isDeleted
      ? { ...e, isDeleted: true, version: (e.version ?? 0) + 1 }
      : e,
  );
}
