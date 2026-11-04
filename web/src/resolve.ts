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

/**
 * The op id a live draft element belongs to, or null. The one place the id-prefix invariant lives:
 * `customData` is client-writable, so the tag alone never counts; the id must carry `<op_id>:`.
 */
export function draftOpId(e: DraftElement): string | null {
  const opId = e.customData?.op_id;
  if (e.isDeleted || !e.customData?.draft || typeof opId !== "string") return null;
  return e.id.startsWith(`${opId}:`) ? opId : null;
}

/** Ops that still have live draft elements in the scene, in scene order. */
export function draftOps(els: readonly DraftElement[]): { opId: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const e of els) {
    const opId = draftOpId(e);
    if (opId !== null) counts.set(opId, (counts.get(opId) ?? 0) + 1);
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

/** Message for an op the server does not hold as `applied` yet. */
export const NOT_READY = "not ready";

/** Run `fn` with an abort signal that fires after TIMEOUT_MS. */
async function withTimeout<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    return await fn(ctl.signal);
  } finally {
    clearTimeout(timer);
  }
}

const failAll = (opIds: string[], message: string): ResolveSummary => ({
  done: [],
  failed: opIds.map((opId) => ({ opId, message })),
  retry: [],
});

/** PATCH one op to accepted/rejected. Never throws; failures come back as a message. */
export async function patchOp(
  opId: string,
  status: Verdict,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<ResolveResult> {
  try {
    const res = await withTimeout((signal) =>
      fetchFn(`/ops/${encodeURIComponent(opId)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status }),
        signal,
      }),
    );
    if (res.ok) return { ok: true };
    if (res.status === 409) return { ok: false, message: NOT_READY };
    return { ok: false, message: `request failed (${res.status})` };
  } catch {
    return { ok: false, message: "Could not reach the server; try again." };
  }
}

/** Ids of the document's ops the server holds as `applied`, or null if it could not be asked. */
export async function fetchAppliedOps(
  documentId: string,
  fetchFn: typeof fetch = (...a) => fetch(...a),
): Promise<Set<string> | null> {
  try {
    return await withTimeout(async (signal) => {
      const res = await fetchFn(`/documents/${encodeURIComponent(documentId)}/ops?status=applied`, { signal });
      if (!res.ok) return null;
      const body = (await res.json()) as { ops?: { id: string }[] };
      return new Set((body.ops ?? []).map((o) => o.id));
    });
  } catch {
    return null;
  }
}

/** The one patch loop: all PATCHes in flight at once (patchOp never throws); results keep input order. */
async function patchEach(opIds: string[], verdict: Verdict, patch: typeof patchOp): Promise<ResolveSummary> {
  const results = await Promise.all(opIds.map((opId) => patch(opId, verdict)));
  const out: ResolveSummary = { done: [], failed: [], retry: [] };
  results.forEach((r, i) => {
    if (r.ok) out.done.push(opIds[i]);
    else out.failed.push({ opId: opIds[i], message: r.message });
  });
  return out;
}

/** Accepted ops whose PATCH failed: the scene is already final, only the status needs a retry. */
async function patchAccepted(opIds: string[], patch: typeof patchOp): Promise<ResolveSummary> {
  const out = await patchEach(opIds, "accepted", patch);
  out.retry = out.failed.map((f) => f.opId);
  return out;
}

/**
 * Retry an accept whose save or PATCH failed. Re-saves first when `save` is given (the scene was
 * already rewritten locally), then PATCHes `accepted`; a failed save PATCHes nothing.
 */
export async function retryAccept(
  opIds: string[],
  patch: typeof patchOp = patchOp,
  save?: () => Promise<boolean>,
): Promise<ResolveSummary> {
  if (save && !(await save())) return { ...failAll(opIds, "could not save"), retry: opIds };
  return patchAccepted(opIds, patch);
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
    if (!applied) return failAll(opIds, "could not check op status");
    const ready = opIds.filter((id) => applied.has(id));
    const notReady = failAll(opIds.filter((id) => !applied.has(id)), NOT_READY).failed;
    if (ready.length === 0) return { done: [], failed: notReady, retry: [] };
    let els = p.scene();
    for (const id of ready) els = acceptOp(els, `${id}:`);
    p.setScene(els);
    if (!(await p.save())) {
      const out = failAll(ready, "could not save");
      return { ...out, failed: [...out.failed, ...notReady], retry: ready };
    }
    const out = await patchAccepted(ready, p.patch);
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
