// Accept / Reject / Accept all for agent drafts (INK-045), framework-free so Node can test it.
// Both helpers match by the op's server-issued id prefix, never by customData alone: customData
// is client-writable and user ink must never be matched.

import { rejectOp, type DraftElement } from "./drafts.ts";

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

export type Verdict = "accepted" | "rejected";
export type ResolveResult = { ok: true } | { ok: false; message: string };
export type ResolveSummary = {
  done: string[];
  failed: { opId: string; message: string }[];
  /** Accepted-after-save ops whose PATCH failed: the scene is final, only the status needs a retry. */
  retry: string[];
};

const TIMEOUT_MS = 8000;

/** PATCH one op to accepted/rejected. Never throws; failures come back as a message. */
export async function patchOp(
  opId: string,
  status: Verdict,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<ResolveResult> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetchFn(`/ops/${encodeURIComponent(opId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
      signal: ctl.signal,
    });
    if (res.ok) return { ok: true };
    if (res.status === 409) return { ok: false, message: "not ready yet" };
    return { ok: false, message: `request failed (${res.status})` };
  } catch {
    return { ok: false, message: "Could not reach the server; try again." };
  } finally {
    clearTimeout(timer);
  }
}

/** Ids of the document's ops the server holds as `applied`, or null if it could not be asked. */
export async function fetchAppliedOps(
  documentId: string,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<Set<string> | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetchFn(`/documents/${encodeURIComponent(documentId)}/ops?status=applied`, {
      signal: ctl.signal,
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { ops?: { id: string }[] };
    return new Set((body.ops ?? []).map((o) => o.id));
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** The one patch loop: ops one after another; a failure is recorded and the rest still run. */
async function patchEach(opIds: string[], verdict: Verdict, patch: typeof patchOp): Promise<ResolveSummary> {
  const out: ResolveSummary = { done: [], failed: [], retry: [] };
  for (const opId of opIds) {
    const r = await patch(opId, verdict);
    if (r.ok) out.done.push(opId);
    else out.failed.push({ opId, message: r.message });
  }
  return out;
}

/** Re-PATCH `accepted` for ops whose scene was already saved; never touches the scene. */
export async function retryAccept(opIds: string[], patch: typeof patchOp = patchOp): Promise<ResolveSummary> {
  const out = await patchEach(opIds, "accepted", patch);
  out.retry = out.failed.map((f) => f.opId);
  return out;
}

export interface Ports {
  scene(): DraftElement[];
  setScene(els: DraftElement[]): void;
  /** Flush the autosave and report whether the scene settled on the server. */
  save(): Promise<boolean>;
  patch: typeof patchOp;
  /** Ops the server holds as `applied`; null when the check failed. */
  appliedOps(): Promise<Set<string> | null>;
}

/**
 * Apply a verdict to ops in a safe order. Accept: rewrite locally, save, THEN PATCH, so a failed
 * save can never leave stored elements tagged draft under an accepted op. Reject: PATCH first,
 * then sweep only the ops the server accepted, so a failure leaves the drafts to retry.
 */
export async function applyVerdict(
  opIds: string[],
  verdict: Verdict,
  p: Ports,
): Promise<ResolveSummary> {
  if (verdict === "accepted") {
    const applied = await p.appliedOps();
    if (!applied)
      return {
        done: [],
        failed: opIds.map((opId) => ({ opId, message: "could not check op status" })),
        retry: [],
      };
    const ready = opIds.filter((id) => applied.has(id));
    const notReady = opIds.filter((id) => !applied.has(id)).map((opId) => ({ opId, message: "not ready" }));
    if (ready.length === 0) return { done: [], failed: notReady, retry: [] };
    let els = p.scene();
    for (const id of ready) els = acceptOp(els, `${id}:`);
    p.setScene(els);
    if (!(await p.save()))
      return {
        done: [],
        failed: [...ready.map((opId) => ({ opId, message: "could not save" })), ...notReady],
        retry: [],
      };
    const out = await patchEach(ready, "accepted", p.patch);
    out.retry = out.failed.map((f) => f.opId);
    out.failed.push(...notReady);
    return out;
  }
  const out = await patchEach(opIds, "rejected", p.patch);
  if (out.done.length) {
    let els = p.scene();
    for (const id of out.done) els = rejectOp(els, `${id}:`);
    p.setScene(els);
  }
  return out;
}
