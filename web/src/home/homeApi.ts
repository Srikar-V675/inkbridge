// Fetch wrappers for the canvases home (INK-118). `f` is injectable so tests need no network.
import type { CanvasSummary } from "./homeLogic.ts";

export type ArchivedFilter = "false" | "true" | "all";

/** The server's detail as one sentence: a string, {msg}, or the first validation error. */
function detailText(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  if (detail && typeof detail === "object" && typeof (detail as { msg?: unknown }).msg === "string") {
    return (detail as { msg: string }).msg;
  }
  return `Request failed (${status})`;
}

async function send<T>(f: typeof fetch, url: string, method: string, body?: unknown): Promise<T> {
  const r = await f(url, {
    method,
    ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!r.ok) {
    const j: { detail?: unknown } = await r.json().catch(() => ({}));
    throw new Error(detailText(j.detail, r.status));
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const listCanvases = (f: typeof fetch, archived: ArchivedFilter): Promise<CanvasSummary[]> =>
  send(f, `/documents?archived=${archived}`, "GET");
const patch = (f: typeof fetch, id: string, body: object): Promise<CanvasSummary> =>
  send(f, `/documents/${encodeURIComponent(id)}`, "PATCH", body);
export const renameCanvas = (f: typeof fetch, id: string, title: string) => patch(f, id, { title });
export const pinCanvas = (f: typeof fetch, id: string, pinned: boolean) => patch(f, id, { pinned });
export const archiveCanvas = (f: typeof fetch, id: string, archived: boolean) => patch(f, id, { archived });
export const duplicateCanvas = (f: typeof fetch, id: string): Promise<CanvasSummary> =>
  send(f, `/documents/${encodeURIComponent(id)}/duplicate`, "POST");
export const createCanvas = (f: typeof fetch, title: string): Promise<CanvasSummary> => send(f, "/documents", "POST", { title });

/** The version in the query makes a new thumbnail replace the cached one after an edit. */
export const thumbnailUrl = (c: Pick<CanvasSummary, "id" | "version">): string =>
  `/documents/${encodeURIComponent(c.id)}/thumbnail?v=${c.version}`;
