// Pure helpers for the canvases home (INK-118). No React, no fetch.
export interface CanvasSummary {
  id: string;
  title: string;
  updated_at: string;
  version: number;
  url: string;
  pinned: boolean;
  archived: boolean;
  element_count: number;
  chunk_count: number;
  open_offers: number;
  last_opened_at: string | null;
}

export interface HomeSections {
  continue: CanvasSummary | null;
  recent: CanvasSummary[];
  all: CanvasSummary[];
}

const time = (iso: string | null) => (iso ? Date.parse(iso) : 0);
const byUpdated = (a: CanvasSummary, b: CanvasSummary) => time(b.updated_at) - time(a.updated_at);
const touched = (c: CanvasSummary) => Math.max(time(c.last_opened_at), time(c.updated_at));

export const RECENT_COUNT = 4;

/** Continue (last touched), Recent (next four by edit time) and All (pinned first). A search shows All only. */
export function homeSections(canvases: CanvasSummary[], query: string, _now: Date): HomeSections {
  const live = canvases.filter((c) => !c.archived);
  const q = query.trim().toLowerCase();
  const all = live
    .filter((c) => !q || c.title.toLowerCase().includes(q))
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || byUpdated(a, b));
  if (q) return { continue: null, recent: [], all };
  const cont = [...live].sort((a, b) => touched(b) - touched(a))[0] ?? null;
  const recent = live.filter((c) => c !== cont).sort(byUpdated).slice(0, RECENT_COUNT);
  return { continue: cont, recent, all };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const DAY = 24 * 60 * 60 * 1000;

/** "12 minutes ago", "Yesterday", "3 Nov" (with the year when it is not this one). */
export function relativeTime(iso: string, now: Date): string {
  const then = new Date(iso);
  const diff = now.getTime() - then.getTime();
  if (diff < 60_000) return "Just now";
  if (dayStart(then) === dayStart(now)) {
    const mins = Math.floor(diff / 60_000);
    return mins < 60 ? `${plural(mins, "minute")} ago` : `${plural(Math.floor(mins / 60), "hour")} ago`;
  }
  if (dayStart(now) - dayStart(then) === DAY) return "Yesterday";
  const day = `${then.getDate()} ${MONTHS[then.getMonth()]}`;
  return then.getFullYear() === now.getFullYear() ? day : `${day} ${then.getFullYear()}`;
}

export function canvasMeta(c: CanvasSummary, now: Date): string {
  if (c.element_count === 0) return "No ink yet";
  const when = relativeTime(c.updated_at, now);
  const phrase = when === "Yesterday" || when === "Just now" ? when.toLowerCase() : when;
  return `Edited ${phrase}, ${plural(c.chunk_count, "chunk")}`;
}

export const offerLabel = (n: number): string => (n > 0 ? plural(n, "draft") : "");

export const newCanvasTitle = (now: Date): string => `Untitled, ${now.getDate()} ${MONTHS[now.getMonth()]}`;

/** The home URL for a view: Archived is its own history entry (INK-172, decision 0071). */
export const archivedHref = (on: boolean) => (on ? "/?view=archived" : "/");
