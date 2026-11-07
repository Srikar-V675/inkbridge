// Open offers, Focus and the waiting count for one canvas (INK-131, decision 0097).
import type { Offer } from "./offers.ts";

export interface OfferState {
  offers: Offer[];
  focus: boolean;
  waiting: number;
}

export function createOfferStore() {
  let state: OfferState = { offers: [], focus: false, waiting: 0 };
  const listeners = new Set<() => void>();
  const put = (next: Partial<OfferState>) => {
    state = { ...state, ...next };
    listeners.forEach((l) => l());
  };
  return {
    get: () => state,
    subscribe(l: () => void) {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    set: (offers: Offer[], waiting: number) => put({ offers: offers.filter((o) => o.status === "open"), waiting }),
    upsert(o: Offer) {
      const rest = state.offers.filter((x) => x.id !== o.id);
      put({ offers: o.status === "open" ? [...rest, o] : rest });
    },
    remove: (id: string) => put({ offers: state.offers.filter((o) => o.id !== id) }),
    setFocus: (focus: boolean) => put({ focus }),
  };
}
export type OfferStore = ReturnType<typeof createOfferStore>;
