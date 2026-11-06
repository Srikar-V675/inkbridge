// In-app navigation without a page load (INK-118, decision 0069). No React here.
export const NAVIGATE_EVENT = "inkbridge:navigate";

export interface TitleHint { canvas: string; title: string }
// What each history entry remembers: the URL it was pushed from, and the canvas title the home already had.
interface NavState { prev?: string; hint?: TitleHint }

type Win = Pick<Window, "location" | "dispatchEvent" | "addEventListener" | "removeEventListener"> & {
  history: Pick<History, "pushState" | "replaceState" | "back" | "state">;
};

const urlOf = (loc: { pathname: string; search: string }) => loc.pathname + loc.search;
const normal = (url: string) => urlOf(new URL(url, "http://x"));

/** Move to a same-origin URL with pushState (or replaceState) and tell subscribers. Same URL = no-op. */
export function navigate(url: string, opts: { replace?: boolean; hint?: TitleHint } = {}, win: Win = window): void {
  const here = urlOf(win.location);
  const target = normal(url);
  if (target === here) return;
  const old = (win.history.state ?? {}) as NavState;
  if (opts.replace) win.history.replaceState({ prev: old.prev, hint: opts.hint } satisfies NavState, "", target);
  else win.history.pushState({ prev: here, hint: opts.hint } satisfies NavState, "", target);
  win.dispatchEvent(new Event(NAVIGATE_EVENT));
}

/** "Back" links: when the entry before this one is `url` (we came from there), step back so the
 *  stack does not grow and browser Back keeps meaning what the screen says; otherwise push it. */
export function backTo(url: string, win: Win = window): void {
  const target = normal(url);
  if (((win.history.state ?? {}) as NavState).prev === target) win.history.back();
  else navigate(target, {}, win);
}

/** The title the home passed along for this canvas, or null (reload keeps it; a plain link has none). */
export function titleHint(canvas: string, win: Pick<Window, "history"> = window): string | null {
  const h = ((win.history.state ?? {}) as NavState).hint;
  return h && h.canvas === canvas && h.title ? h.title : null;
}

/** Call cb after every navigate() and on Back/Forward. Returns the unsubscribe function. */
export function subscribe(cb: () => void, win: Win = window): () => void {
  win.addEventListener(NAVIGATE_EVENT, cb);
  win.addEventListener("popstate", cb);
  return () => {
    win.removeEventListener(NAVIGATE_EVENT, cb);
    win.removeEventListener("popstate", cb);
  };
}

type LinkClick = {
  button: number;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  preventDefault(): void;
  currentTarget: { origin: string; pathname: string; search: string; target: string };
};

/** onClick for an <a href>: a plain left click navigates in place; new tab, copy link and
 *  modified clicks keep the browser's behaviour. */
export function onLinkClick(
  e: LinkClick,
  nav: (url: string) => void = navigate,
  origin: string = window.location.origin,
): void {
  const a = e.currentTarget;
  if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  if ((a.target && a.target !== "_self") || a.origin !== origin) return;
  e.preventDefault();
  nav(a.pathname + a.search);
}
