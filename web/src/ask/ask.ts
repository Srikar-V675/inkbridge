// Framework-free client and helpers for the Ask AI panel (INK-049, docs/decisions/0046).
// answer_md is untrusted (decision 0035): plainText strips it before it reaches an agent op.
import { resolveChunk } from "../chunks/chunks.ts";

export interface Source {
  type: "chunk" | "note";
  id?: string;
  path?: string;
}
export interface Question {
  id: string;
  document_id: string;
  parent_id: string | null;
  text: string;
  focus_element_ids: string[];
  focus_chunk_ids: string[];
  status: "pending" | "answered" | "cancelled" | string;
  answer_md: string | null;
  canvas_text: string | null;
  sources: Source[];
  created_at: string;
  runner_status: "pending" | "running" | "failed";
  runner_error: string | null;
}

export function applyQuestionUpdate(list: Question[], q: Question): Question[] {
  const i = list.findIndex((x) => x.id === q.id);
  if (i < 0) return [...list, q]; // the list is oldest first
  const next = list.slice();
  next[i] = q;
  return next;
}

// App.tsx feeds the socket into this; AskPanel listens. null = refetch (the socket reconnected).
type Listener = (q: Question | null) => void;
const listeners = new Set<Listener>();
export function subscribeQuestions(fn: Listener): () => void {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}
export function publishQuestion(q: Question | null) {
  listeners.forEach((fn) => fn(q));
}

/** Runner state of a pending question (INK-103 fields). The reason is path-free server text. */
export function runnerLine(q: Question): string | null {
  if (q.status !== "pending") return null;
  if (q.runner_status === "failed") return `The answering agent failed: ${q.runner_error ?? "unknown reason"}`;
  if (q.runner_status === "running") return "Answering...";
  return q.runner_error ? `Retrying after: ${q.runner_error}` : null;
}

export const MAX_FOCUS = 200; // API limit
export const KEEP_CAP = 2000; // chars of plain text sent to write_text
const TIMEOUT_MS = 8000;

export function focusIds(
  scene: readonly { id: string; isDeleted?: boolean; customData?: { draft?: boolean } }[],
  selected: Record<string, boolean>,
): string[] {
  return scene
    .filter((e) => selected[e.id] && !e.isDeleted && !e.customData?.draft)
    .map((e) => e.id)
    .slice(0, MAX_FOCUS);
}

/** Last path segment only: a full vault path must never reach the DOM. */
export function fileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || "note";
}

export function plainText(md: string, cap = KEEP_CAP): string {
  return md
    .replace(/```[^\n]*\n?/g, "")
    .replace(/<\/?[a-zA-Z][^>]*>/g, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_`]+/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, cap);
}

type Fetch = typeof fetch;
const defaultFetch: Fetch = (...a) => fetch(...a);

async function call<T>(f: Fetch, url: string, init: RequestInit = {}): Promise<{ status: number; body: T }> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await f(url, { ...init, signal: ctl.signal });
    const body = (await res.json().catch(() => null)) as T;
    return { status: res.status, body };
  } finally {
    clearTimeout(timer);
  }
}

async function ok<T>(p: Promise<{ status: number; body: T }>): Promise<T> {
  const r = await p;
  if (r.status < 200 || r.status >= 300) throw new Error(String(r.status));
  return r.body;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export function askQuestion(canvas: string, text: string, focus: string[], parentId: string | null = null, f: Fetch = defaultFetch): Promise<Question> {
  const body = { text, focus_element_ids: focus, ...(parentId && { parent_id: parentId }) };
  return ok(call<Question>(f, `/documents/${encodeURIComponent(canvas)}/questions`, post(body)));
}

export async function listQuestions(canvas: string, f: Fetch = defaultFetch): Promise<Question[]> {
  const r = await ok(call<{ questions: Question[] }>(f, `/documents/${encodeURIComponent(canvas)}/questions?limit=100`));
  return r.questions;
}

export function cancelQuestion(id: string, f: Fetch = defaultFetch): Promise<Question> {
  return ok(call<Question>(f, `/questions/${encodeURIComponent(id)}/cancel`, { method: "POST" }));
}

export const CARD_CAP = 300; // chars drawn beside the ink

const firstParagraph = (t: string) => t.split(/\n\s*\n/)[0].trim();

/** The text a Keep draft carries: the agent's canvas summary, else the answer's first paragraph. */
export function cardText(q: Question): string {
  const own = plainText(q.canvas_text ?? "", CARD_CAP);
  return own || firstParagraph(plainText(q.answer_md ?? "")).slice(0, CARD_CAP);
}

export function keepOp(q: Question, anchor: string | null) {
  return {
    type: "write_text" as const,
    op_id: `keep-${q.id}`, // idempotent: a double tap makes one draft
    payload: { text: cardText(q), question_id: q.id, relation: "answer" as const, ...(anchor && { anchor }) },
  };
}

/** Body of the first flowchart block in the answer, else null (no model call: the answer drew it). */
export function mermaidBlock(md: string): string | null {
  for (const m of md.matchAll(/```mermaid[^\S\n]*\n([\s\S]*?)```/g)) {
    const body = m[1].trim();
    if (/^(flowchart|graph)\b/.test(body)) return body;
  }
  return null;
}

export function diagramOp(q: Question, anchor: string | null) {
  const mermaid = mermaidBlock(q.answer_md ?? "");
  if (!mermaid) return null;
  return {
    type: "draw_diagram" as const,
    op_id: `diagram-${q.id}`,
    payload: { mermaid, question_id: q.id, relation: "diagram" as const, ...(anchor && { anchor }) },
  };
}

/** Opens the note by name only: a vault path never reaches the DOM (decision 0046). */
export const noteUrl = (path: string): string =>
  `obsidian://open?file=${encodeURIComponent(fileName(path).replace(/\.md$/i, ""))}`;

async function resolveAnchor(q: Question, canvas: string, f: Fetch): Promise<string | null> {
  const candidates = [...q.focus_chunk_ids, ...q.sources.filter((s) => s.type === "chunk" && s.id).map((s) => s.id!)];
  for (const id of candidates) {
    const r = await resolveChunk(id, canvas, f);
    if (r.chunk?.status === "active") return r.chunk.id;
  }
  return null;
}

async function postDraft(
  q: Question, canvas: string, f: Fetch, make: (anchor: string | null) => object,
): Promise<{ ok: boolean; reason?: string }> {
  const anchor = await resolveAnchor(q, canvas, f);
  const url = `/documents/${encodeURIComponent(canvas)}/ops`;
  try {
    let r = await call<{ status?: string; detail?: { code?: string } }>(f, url, post(make(anchor)));
    if (r.status === 422 && anchor && r.body?.detail?.code === "anchor_gone") r = await call(f, url, post(make(null)));
    if (r.status !== 200 && r.status !== 201) return { ok: false, reason: String(r.status) };
    // A replay (200) returns the stored op: say so if the user already resolved that draft.
    const st = (r.body as { status?: string } | null)?.status;
    return st === "accepted" || st === "rejected" ? { ok: false, reason: `draft already ${st}` } : { ok: true };
  } catch (e) {
    return { ok: false, reason: e instanceof Error ? e.message : "failed" };
  }
}

export async function keepOnCanvas(q: Question, canvas: string, f: Fetch = defaultFetch): Promise<{ ok: boolean; reason?: string }> {
  if (!cardText(q)) return { ok: false, reason: "empty answer" };
  return postDraft(q, canvas, f, (a) => keepOp(q, a));
}

export async function drawDiagram(q: Question, canvas: string, f: Fetch = defaultFetch): Promise<{ ok: boolean; reason?: string }> {
  if (!diagramOp(q, null)) return { ok: false, reason: "no flowchart in the answer" };
  return postDraft(q, canvas, f, (a) => diagramOp(q, a)!);
}
