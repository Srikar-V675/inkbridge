// Framework-free chunk lookups and viewport maths for the deep link and the chunk overlay.
// Deep link contract: /?canvas=<document id>&chunk=<chunk id> (docs/decisions/0013).
// Only plain fetch and DOM-free maths: works over LAN HTTP, no secure-context APIs.

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Chunk {
  id: string;
  document_id: string;
  element_ids: string[];
  bounds: Bounds;
  status: "active" | "orphaned" | string;
  successor_of: string | null;
  created_by?: string;
}

export type JumpOutcome = "found" | "successor" | "orphaned" | "missing" | "error";

export interface JumpResult {
  outcome: JumpOutcome;
  /** The id from the link. */
  requested: string;
  /** Where to jump: the active chunk, or the last orphan reached (its old bounds). */
  chunk: Chunk | null;
}

export interface View {
  scrollX: number;
  scrollY: number;
  zoom: number;
}

const MAX_HOPS = 10;
const TIMEOUT_MS = 8000;

class NotFound extends Error {}

/** fetch with a timeout (AbortController works in insecure contexts), so a stalled API ends as "error". */
async function fetchWithTimeout(fetchFn: typeof fetch, url: string): Promise<Response> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    return await fetchFn(url, { signal: ctl.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function getChunk(id: string, fetchFn: typeof fetch): Promise<Chunk> {
  const res = await fetchWithTimeout(fetchFn, `/regions/${encodeURIComponent(id)}`);
  if (res.status === 404) throw new NotFound(id);
  if (!res.ok) throw new Error(`GET /regions/${id}: ${res.status}`);
  return (await res.json()) as Chunk;
}

/**
 * Resolve a deep-linked chunk id: an orphaned chunk follows `successor_of` (tech ref 5.8) until an
 * active chunk, a dead end or a cycle. A dead end keeps the last orphan so the app can open at its
 * old bounding box. Ids that are unknown, manual regions or on another canvas are "missing".
 */
export async function resolveChunk(
  id: string,
  canvas: string,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<JumpResult> {
  let current: Chunk;
  try {
    current = await getChunk(id, fetchFn);
  } catch (e) {
    return { outcome: e instanceof NotFound ? "missing" : "error", requested: id, chunk: null };
  }
  if (current.document_id !== canvas || current.created_by !== "auto") {
    return { outcome: "missing", requested: id, chunk: null };
  }
  const seen = new Set([current.id]);
  for (let hop = 0; hop < MAX_HOPS && current.status !== "active"; hop++) {
    const next = current.successor_of;
    if (!next || seen.has(next)) break;
    seen.add(next);
    try {
      const succ = await getChunk(next, fetchFn);
      if (succ.document_id !== canvas) break;
      current = succ;
    } catch {
      break; // the chain is broken: open at the last orphan we have
    }
  }
  if (current.status === "active") {
    return { outcome: current.id === id ? "found" : "successor", requested: id, chunk: current };
  }
  return { outcome: "orphaned", requested: id, chunk: current };
}

/** Banner text for a jump; null when the link resolved to the chunk it named. */
export function jumpNotice(r: JumpResult): string | null {
  switch (r.outcome) {
    case "found":
      return null;
    case "successor":
      return `Source changed: chunk ${r.requested} was replaced, showing ${r.chunk?.id}.`;
    case "orphaned":
      return `Source changed: chunk ${r.requested} no longer exists, showing where it was.`;
    case "missing":
      return `Chunk ${r.requested} not found on this canvas.`;
    case "error":
      return `Could not load chunk ${r.requested}; check the connection and reload.`;
  }
}

/**
 * Active chunks of a canvas for the overlay. Uses `?chunks=true` on the regions list until INK-033
 * ships `GET /documents/{id}/chunks`; only this function changes then. Failures give an empty list.
 * Known limit: the server applies `limit` before this status filter and orders by recency, so a canvas
 * with more than 500 chunk rows (orphans included) can miss active ones; INK-033 removes this.
 */
export async function listChunks(
  canvas: string,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<Chunk[]> {
  try {
    const res = await fetchWithTimeout(fetchFn, `/documents/${encodeURIComponent(canvas)}/regions?chunks=true&limit=500`);
    if (!res.ok) return [];
    const rows = (await res.json()) as Chunk[];
    return rows.filter((c) => c.status === "active");
  } catch {
    return [];
  }
}

/** The chunk's element ids that are in the scene and not deleted (the server may be ahead or behind). */
export function liveIds(chunk: Chunk, scene: readonly { id: string; isDeleted?: boolean }[]): string[] {
  const live = new Set(scene.filter((e) => !e.isDeleted).map((e) => e.id));
  return chunk.element_ids.filter((id) => live.has(id));
}

/** Scroll and zoom that centre `b` in the viewport with a 10% margin, never zooming above 100%. */
export function viewForBounds(b: Bounds, viewport: { width: number; height: number }): View {
  const w = Math.max(b.width, 1);
  const h = Math.max(b.height, 1);
  const zoom = Math.max(0.1, Math.min(1, (viewport.width * 0.9) / w, (viewport.height * 0.9) / h));
  return {
    zoom,
    scrollX: viewport.width / (2 * zoom) - (b.x + b.width / 2),
    scrollY: viewport.height / (2 * zoom) - (b.y + b.height / 2),
  };
}

/** Scene bounds to CSS pixels relative to the canvas container (Excalidraw: screen = (scene + scroll) * zoom). */
export function toScreen(b: Bounds, v: View) {
  return {
    left: (b.x + v.scrollX) * v.zoom,
    top: (b.y + v.scrollY) * v.zoom,
    width: b.width * v.zoom,
    height: b.height * v.zoom,
  };
}
