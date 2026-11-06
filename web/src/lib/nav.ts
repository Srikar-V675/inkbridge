// In-app navigation without a page load (INK-118, decision 0069). No React here.
export const NAVIGATE_EVENT = "inkbridge:navigate";

type Win = Pick<Window, "location" | "history" | "dispatchEvent" | "addEventListener" | "removeEventListener">;

/** Move to a same-origin URL with pushState (or replaceState) and tell subscribers. Same URL = no-op. */
export function navigate(url: string, opts: { replace?: boolean } = {}, win: Win = window): void {
  const here = win.location.pathname + win.location.search;
  const next = new URL(url, "http://x");
  if (next.pathname + next.search === here) return;
  const target = next.pathname + next.search;
  if (opts.replace) win.history.replaceState(null, "", target);
  else win.history.pushState(null, "", target);
  win.dispatchEvent(new Event(NAVIGATE_EVENT));
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
