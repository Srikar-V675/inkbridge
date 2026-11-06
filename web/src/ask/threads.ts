// Thread grouping and copy for the Ask panel (INK-161, docs/decisions/0067). Pure so Node tests import it.
import { MAX_FOCUS, plainText, runnerLine, type Question } from "./ask.ts";

export interface Thread { id: string; items: Question[] } // items: oldest first

function rootId(byId: Map<string, Question>, q: Question): string {
  const seen = new Set<string>();
  let cur = q;
  while (cur.parent_id && byId.has(cur.parent_id) && !seen.has(cur.id)) {
    seen.add(cur.id);
    cur = byId.get(cur.parent_id)!;
  }
  return cur.id;
}

/** `list` is oldest first (the API order). Result: newest activity first. */
export function groupThreads(list: Question[]): Thread[] {
  const byId = new Map(list.map((q) => [q.id, q]));
  const groups = new Map<string, { items: Question[]; last: number }>();
  list.forEach((q, i) => {
    const id = rootId(byId, q);
    const g = groups.get(id) ?? { items: [], last: 0 };
    g.items.push(q);
    g.last = i;
    groups.set(id, g);
  });
  return [...groups.entries()].sort((a, b) => b[1].last - a[1].last).map(([id, g]) => ({ id, items: g.items }));
}

export const replyTarget = (t: Thread): Question => t.items[t.items.length - 1];
export const threadTitle = (t: Thread): string => t.items[0].text;
export const messageCount = (t: Thread): number => t.items.length + t.items.filter((q) => q.status === "answered").length;

export function firstLine(md: string): string {
  return plainText(md).split("\n").map((l) => l.trim()).find(Boolean)?.slice(0, 200) ?? "";
}

/** One line under the thread title, from the latest question. `failed` selects the alarm colour. */
export function threadLine(t: Thread): { text: string; failed: boolean } {
  const q = replyTarget(t);
  if (q.status === "pending") return { text: runnerLine(q) ?? "Waiting for an agent", failed: q.runner_status === "failed" };
  if (q.status === "cancelled") return { text: "Cancelled", failed: false };
  if (q.status === "answered") return { text: firstLine(q.answer_md ?? "") || "Answered", failed: false };
  return { text: q.status, failed: false };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dayNumber = (d: Date) => Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 86_400_000);

export function relativeTime(iso: string, now: number): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const diff = now - at;
  if (diff < 60_000) return "Just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} min ago`;
  const days = dayNumber(new Date(now)) - dayNumber(new Date(at));
  if (days <= 0) return `${Math.floor(diff / 3_600_000)} h ago`;
  if (days === 1) return "Yesterday";
  const d = new Date(at);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function canSend(s: { text: string; busy: boolean; selected: number; followUp: boolean }): boolean {
  return !s.busy && s.text.trim().length > 0 && (s.followUp || s.selected > 0);
}

export function scopeLine(selected: number, raw: number): string {
  if (!selected) return "Nothing selected yet";
  return `About ${selected} selected element${selected === 1 ? "" : "s"}${raw > MAX_FOCUS ? ", capped at 200" : ""}`;
}
