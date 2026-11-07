// Pure helpers that turn an agent op into draft elements (tech ref 9.9). No Excalidraw import, so
// they run under Node's test runner; App.tsx supplies the Excalidraw/Mermaid conversion.
//
// Rules: drafts only ever ADD elements. Every element an op creates gets an id starting with the
// op's server-issued `id_prefix` (the server refuses any other id in the ack, decision 0009), is
// tagged customData {author:"agent", draft:true, op_id} and drawn dashed. User elements are never
// touched; the scene's drafts are a function of the placed-op list (draftStore.reconcile).

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
    font_size?: number;
    wrap_chars?: number;
    placement?: Placement;
    anchor_resolved?: string | null;
    id_prefix: string;
  };
}

/** Font size the server computed from the handwriting; ops stored before it existed were 20. */
export function opFontSize(payload: { font_size?: number }): number {
  const f = payload.font_size;
  return typeof f === "number" && f > 0 ? Math.min(2000, Math.round(f)) : 20;
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

/** Bbox of the elements (arrows by their points) and its size. */
function extent(elements: readonly DraftElement[]) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const e of elements) {
    const xs = e.points?.length ? e.points.map((p) => e.x + p[0]) : [e.x, e.x + (e.width ?? 0)];
    const ys = e.points?.length ? e.points.map((p) => e.y + p[1]) : [e.y, e.y + (e.height ?? 0)];
    x0 = Math.min(x0, ...xs); x1 = Math.max(x1, ...xs);
    y0 = Math.min(y0, ...ys); y1 = Math.max(y1, ...ys);
  }
  return elements.length ? { width: x1 - x0, height: y1 - y0 } : { width: 0, height: 0 };
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

/** What the browser sends back for the server to place: prefixed elements and their size (the server places, INK-114). */
export function measureDrafts<T extends DraftElement>(converted: readonly T[], op: PendingOp): { elements: T[]; width: number; height: number } {
  const elements = prefixIds(converted, op.payload.id_prefix);
  return { elements, ...extent(elements) };
}

/**
 * The op id a live draft element belongs to, or null. The one place the id-prefix invariant lives:
 * `customData` is client-writable, so the tag alone never counts; the id must carry `<op_id>:`.
 */
export function draftOpId(e: DraftElement): string | null {
  const opId = e.customData?.op_id;
  if (e.isDeleted || !e.customData?.draft || typeof opId !== "string") return null;
  return e.id.startsWith(`${opId}:`) ? opId : null;
}

/** Like draftOpId but also true for a soft-deleted draft: the sender must never see either. */
export function isDraftTagged(e: Pick<DraftElement, "id" | "customData">): boolean {
  const opId = e.customData?.op_id;
  return !!e.customData?.draft && typeof opId === "string" && e.id.startsWith(`${opId}:`);
}

/** Break `text` into lines of at most `maxChars` (spaces first, long words hard-split). */
export function wrapText(text: string, maxChars?: number): string {
  if (!maxChars || maxChars <= 0) return text;
  return text
    .split("\n")
    .map((line) => {
      const out: string[] = [];
      let cur = "";
      for (const word of line.split(" ")) {
        let w = word;
        while (w.length > maxChars) {
          if (cur) {
            out.push(cur);
            cur = "";
          }
          out.push(w.slice(0, maxChars));
          w = w.slice(maxChars);
        }
        if (cur && cur.length + 1 + w.length > maxChars) {
          out.push(cur);
          cur = w;
        } else cur = cur ? `${cur} ${w}` : w;
      }
      out.push(cur);
      return out.join("\n");
    })
    .join("\n");
}
