// Manual chunk merge and split (INK-059, docs/decisions/0017). Framework-free: what the current
// selection means for the chunks, and the request that applies it. The server owns overrides;
// nothing here touches the scene.
import type { Chunk } from "./chunks";

export type OverridePlan =
  | { kind: "merge"; chunkIds: string[] }
  | { kind: "split"; chunkId: string; elementIds: string[] }
  | { kind: "none"; reason: string };

export type OverrideResult = { ok: true; ids: string[] } | { ok: false; message: string };

const TIMEOUT_MS = 8000;

/**
 * Selection spanning two or more chunks: merge those chunks (whole). Part of one chunk: split that
 * part off. Selected ids in no chunk (drafts, ink not saved yet) are ignored, and so are
 * `connectors` (arrows, lines and their labels): the server keeps them with the chunk they start
 * from, so only ink decides what a selection means.
 */
export function planOverride(
  selected: readonly string[],
  chunks: readonly Chunk[],
  connectors: ReadonlySet<string> = new Set(),
): OverridePlan {
  const picked = new Set(selected.filter((id) => !connectors.has(id)));
  const ink = (c: Chunk) => c.element_ids.filter((id) => !connectors.has(id));
  const touched = chunks.filter((c) => ink(c).some((id) => picked.has(id)));
  if (touched.length === 0) return { kind: "none", reason: "Select ink that belongs to a chunk." };
  if (touched.length > 1) return { kind: "merge", chunkIds: touched.map((c) => c.id) };
  const [c] = touched;
  const part = ink(c).filter((id) => picked.has(id)).sort();
  if (part.length === ink(c).length) {
    return { kind: "none", reason: "The selection already is a whole chunk." };
  }
  return { kind: "split", chunkId: c.id, elementIds: part };
}

/** Arrows, lines and the text bound to them: they follow their ends and are never split or merged. */
export function connectorIds(
  scene: readonly { id: string; type?: string; containerId?: string | null }[],
): Set<string> {
  const lines = new Set(scene.filter((e) => e.type === "arrow" || e.type === "line").map((e) => e.id));
  for (const e of scene) if (e.containerId && lines.has(e.containerId)) lines.add(e.id);
  return lines;
}

/** POST the override; the result names the new chunk ids or says why it was refused. */
export async function sendOverride(
  canvas: string,
  plan: OverridePlan,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<OverrideResult> {
  if (plan.kind === "none") return { ok: false, message: plan.reason };
  const body =
    plan.kind === "merge" ? { chunk_ids: plan.chunkIds } : { chunk_id: plan.chunkId, element_ids: plan.elementIds };
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetchFn(`/documents/${encodeURIComponent(canvas)}/chunks/${plan.kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    });
    const data = (await res.json().catch(() => ({}))) as {
      chunk?: { id: string };
      chunks?: { id: string }[];
      detail?: unknown;
    };
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `request failed (${res.status})`;
      return { ok: false, message: detail };
    }
    const ids = data.chunk ? [data.chunk.id] : (data.chunks ?? []).map((c) => c.id);
    return { ok: true, ids };
  } catch {
    return { ok: false, message: "Could not reach the server; try again." };
  } finally {
    clearTimeout(timer);
  }
}
