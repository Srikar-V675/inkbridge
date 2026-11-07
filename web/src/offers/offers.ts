// Framework-free offers client and helpers (INK-131, decision 0097). Fetch is injected like ask.ts.
export interface Offer {
  id: string;
  document_id: string;
  kind: string;
  anchor_chunk: string;
  reason: string;
  payload: Record<string, unknown>;
  score: number;
  status: string;
}

export type Popover = "related" | "answer" | "generic";
export const popoverKind = (o: Offer): Popover =>
  o.kind === "related" ? "related" : o.kind === "answer_ready" || typeof o.payload.question_id === "string" ? "answer" : "generic";
export const chipLabel = (o: Offer): string => ({ related: "Related note", answer: "Answer ready", generic: o.reason })[popoverKind(o)];

export const obsidianUrl = (vault: string, file: string) =>
  `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
export const canvasLink = (origin: string, doc: string, chunk?: string) =>
  `${origin}/?canvas=${encodeURIComponent(doc)}${chunk ? `&chunk=${encodeURIComponent(chunk)}` : ""}`;

/** One transform for all chips: screen = (p + scroll) * zoom. Chips undo the scale with --z. */
export const planeStyle = (v: { scrollX: number; scrollY: number; zoom: number }) => ({
  transform: `scale(${v.zoom}) translate(${v.scrollX}px, ${v.scrollY}px)`,
  z: String(v.zoom),
});

/** One line per link: a canvas URL, or a plain label for an Ask thread. */
export const linksText = (o: Offer, origin: string): string => {
  const p = o.payload;
  if (typeof p.other_document === "string")
    return canvasLink(origin, p.other_document, typeof p.other_chunk === "string" ? p.other_chunk : undefined);
  return typeof p.other_question === "string" ? `Ask thread ${p.other_question}` : "";
};

type Fetch = typeof fetch;
const defaultFetch: Fetch = (...a) => fetch(...a);
const TIMEOUT_MS = 8000;
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body !== undefined && { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
});

async function call(f: Fetch, url: string, init: RequestInit, okStatus: (s: number) => boolean = (s) => s >= 200 && s < 300) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await f(url, { ...init, signal: ctl.signal });
    if (!okStatus(res.status)) throw new Error(String(res.status));
    return (await res.json().catch(() => null)) as unknown;
  } finally {
    clearTimeout(timer);
  }
}

const doc = (canvas: string) => `/documents/${encodeURIComponent(canvas)}`;

export async function listOffers(canvas: string, f: Fetch = defaultFetch): Promise<{ offers: Offer[]; waiting: number; focus: boolean }> {
  const r = (await call(f, `${doc(canvas)}/offers?status=open`, {})) as { offers: Offer[]; waiting?: number; focus?: boolean };
  return { offers: r.offers, waiting: r.waiting ?? 0, focus: r.focus === true };
}

/** A tap on an offer that is no longer open (409) is fine: the chip is stale, not broken. */
export const tapOffer = (id: string, f: Fetch = defaultFetch) =>
  call(f, `/offers/${encodeURIComponent(id)}/tap`, json("POST"), (s) => (s >= 200 && s < 300) || s === 409).then(() => {});
export const dismissOffer = (id: string, f: Fetch = defaultFetch) =>
  call(f, `/offers/${encodeURIComponent(id)}/dismiss`, json("POST")).then(() => {});
export const setFocus = (canvas: string, on: boolean, f: Fetch = defaultFetch) =>
  call(f, `${doc(canvas)}/focus`, json("PUT", { on })).then(() => {});

/** "Add links beside": a write_text draft through the normal op queue; the user accepts it as usual. */
export const addLinks = (o: Offer, origin: string, f: Fetch = defaultFetch) =>
  call(
    f,
    `${doc(o.document_id)}/ops`,
    json("POST", { type: "write_text", payload: { text: linksText(o, origin), anchor: o.anchor_chunk, size: "small" } }),
  ).then(() => {});
