// Pure text for the draft UI (INK-162), kept out of DraftBar.tsx so Node can test it.
import type { DraftElement } from "./drafts.ts";
import { draftOpId, NOT_READY, type ResolveSummary, type Verdict } from "./resolve.ts";

export const trayLabel = (n: number): string => `${n} ${n === 1 ? "draft" : "drafts"} on this canvas`;

/** The failure line under the tray (moved from DraftBar.report, same wording). */
export function failureText(summary: ResolveSummary): string {
  const notReady = summary.failed.filter((f) => f.message === NOT_READY).length;
  const others = summary.failed.filter((f) => f.message !== NOT_READY).map((f) => f.message);
  return [...(notReady ? [`${notReady} not ready`] : []), ...new Set(others)].join("; ");
}

/** Toast after a verdict; null when nothing was resolved (failures show in the failure line instead). */
export function verdictToast(verdict: Verdict, summary: Pick<ResolveSummary, "done">): string | null {
  const n = summary.done.length;
  if (n === 0) return null;
  if (verdict === "accepted") return n === 1 ? "Added to your canvas" : `Added ${n} drafts to your canvas`;
  return n === 1 ? "Draft removed." : `${n} drafts removed.`;
}

/** Where Jump goes: the oldest unseen draft, else the first draft. */
export function jumpTarget(unseen: readonly string[], drafts: readonly { opId: string }[]): string | null {
  return unseen[0] ?? drafts[0]?.opId ?? null;
}

const PREVIEW_MAX = 200;

/** Kind and text preview of one op's live drafts. Matches through `draftOpId`, never the tag alone. */
export function draftCard(els: readonly DraftElement[], opId: string): { kind: "text" | "diagram"; preview: string } {
  const mine = els.filter((e) => draftOpId(e) === opId);
  const texts = mine.filter((e) => e.type === "text");
  const kind = mine.length > 0 && texts.length === mine.length ? "text" : "diagram";
  if (kind === "diagram") return { kind, preview: "" };
  const joined = texts.map((e) => (typeof e.text === "string" ? e.text : "")).join(" ").replace(/\s+/g, " ").trim();
  const preview = joined.length > PREVIEW_MAX ? `${joined.slice(0, PREVIEW_MAX - 1).trimEnd()}…` : joined;
  return { kind, preview };
}
