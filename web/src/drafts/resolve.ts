// Accept / Reject / Undo for agent drafts (INK-115, decision 0090). The server owns the verdict;
// these only call it. Never throws: failures come back as a message.
import type { PlacedOp } from "./draftStore.ts";

export type ResolveResult = { ok: true; op: unknown } | { ok: false; message: string };

const TIMEOUT_MS = 8000;
type Fetch = typeof fetch;
const realFetch: Fetch = (...a) => fetch(...a);

async function post(url: string, body: unknown, fetchFn: Fetch): Promise<ResolveResult> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetchFn(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body ?? {}),
      signal: ctl.signal,
    });
    if (res.ok) return { ok: true, op: ((await res.json().catch(() => ({}))) as { op?: unknown }).op };
    const detail = await res.json().then((j: { detail?: unknown }) => j?.detail, () => undefined);
    const code = typeof detail === "string" ? detail : (detail as { code?: string } | undefined)?.code;
    if (res.status === 409 && code === "window_closed") return { ok: false, message: "Too late to undo" };
    return { ok: false, message: `request failed (${res.status})` };
  } catch {
    return { ok: false, message: "Could not reach the server; try again." };
  } finally {
    clearTimeout(timer);
  }
}

const route = (opId: string, verb: string) => `/ops/${encodeURIComponent(opId)}/${verb}`;

export const accept = (opId: string, dx: number, dy: number, f: Fetch = realFetch) =>
  post(route(opId, "accept"), { dx, dy }, f);
export const reject = (opId: string, f: Fetch = realFetch) => post(route(opId, "reject"), {}, f);
export const unaccept = (opId: string, f: Fetch = realFetch) => post(route(opId, "unaccept"), {}, f);

/** The placed drafts of a canvas, or [] when the server cannot be asked. */
export async function fetchDrafts(documentId: string, f: Fetch = realFetch): Promise<PlacedOp[]> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await f(`/documents/${encodeURIComponent(documentId)}/drafts`, { signal: ctl.signal });
    if (!res.ok) return [];
    const body = (await res.json()) as { drafts?: PlacedOp[] } | null;
    return body?.drafts ?? [];
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}
