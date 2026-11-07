// Pure text for the draft UI (INK-162), kept out of DraftBar.tsx so Node can test it.
import type { PlacedOp } from "./draftStore.ts";
import type { ResolveResult } from "./resolve.ts";

export type Verdict = "accepted" | "rejected";

export const trayLabel = (n: number): string => `${n} ${n === 1 ? "draft" : "drafts"} on this canvas`;

/** The failure line under the tray: distinct messages of the failed calls. */
export function failureText(results: readonly ResolveResult[]): string {
  return [...new Set(results.flatMap((r) => (r.ok ? [] : [r.message])))].join("; ");
}

/** Toast after a verdict; null when nothing was resolved (failures show in the failure line instead). */
export function verdictToast(verdict: Verdict, summary: { done: readonly unknown[] }): string | null {
  const n = summary.done.length;
  if (n === 0) return null;
  if (verdict === "accepted") return n === 1 ? "Added to your canvas" : `Added ${n} drafts to your canvas`;
  return n === 1 ? "Draft removed." : `${n} drafts removed.`;
}

/** Where Jump goes: the oldest unseen draft, else the first draft, skipping any that has no box to pan to. */
export function jumpTarget(
  unseen: readonly string[],
  drafts: readonly { opId: string }[],
  hasBox: (opId: string) => boolean = () => true,
): string | null {
  return [...unseen, ...drafts.map((d) => d.opId)].find(hasBox) ?? null;
}

const PREVIEW_MAX = 200;

/** Kind and text preview of one placed op, read from its elements. */
export function draftCard(op: Pick<PlacedOp, "elements">): { kind: "text" | "diagram"; preview: string } {
  const els = op.elements;
  const kind = els.length > 0 && els.every((e) => e.type === "text") ? "text" : "diagram";
  if (kind === "diagram") return { kind, preview: "" };
  const joined = els.map((e) => (typeof e.text === "string" ? e.text : "")).join(" ").replace(/\s+/g, " ").trim();
  const preview = joined.length > PREVIEW_MAX ? `${joined.slice(0, PREVIEW_MAX - 1).trimEnd()}…` : joined;
  return { kind, preview };
}
