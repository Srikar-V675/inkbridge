import { useMemo, useSyncExternalStore } from "react";
import { subscribe } from "../lib/nav";
import { parseLocation, type Location } from "../lib/route";

/** The current page, re-read after every in-app navigation and Back/Forward. Stable between renders. */
export function useLocation(): Location {
  const search = useSyncExternalStore(subscribe, () => window.location.search);
  return useMemo(() => parseLocation(search), [search]);
}
