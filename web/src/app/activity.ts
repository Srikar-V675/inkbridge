// The working dot's state (INK-198, decision 0113): what the agent is doing on this canvas.
// Framework-free; WorkingDot.tsx subscribes to it.

export interface ActivityMsg {
  type: "agent.activity";
  working: boolean;
  what: "reading" | "task" | "answer";
  count: number;
}

export interface ActivityView {
  visible: boolean;
  label: string;
}

/** The dot lingers this long after the agent goes idle, so a burst of reads does not flicker. */
export const HIDE_MS = 1000;

const LABELS = {
  reading: "Reading your handwriting",
  task: "Working on a task",
  answer: "Answering your question",
} as const;

const HIDDEN: ActivityView = { visible: false, label: "" };

export function createActivityStore(
  setTimer: (fn: () => void, ms: number) => unknown = setTimeout,
  clearTimer: (id: unknown) => void = (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
) {
  let view: ActivityView = HIDDEN;
  let timer: unknown = null;
  const subs = new Set<() => void>();

  const set = (v: ActivityView) => {
    view = v;
    subs.forEach((f) => f());
  };
  const cancel = () => {
    if (timer !== null) clearTimer(timer);
    timer = null;
  };

  return {
    get: (): ActivityView => view,
    subscribe(f: () => void): () => void {
      subs.add(f);
      return () => subs.delete(f);
    },
    apply(m: ActivityMsg): void {
      if (typeof m.working !== "boolean" || !(m.what in LABELS)) return;
      cancel();
      if (m.working) {
        set({ visible: true, label: LABELS[m.what] + (m.count > 1 ? ` (${m.count})` : "") });
      } else if (view.visible) {
        timer = setTimer(() => {
          timer = null;
          set(HIDDEN);
        }, HIDE_MS);
      }
    },
    reset(): void {
      cancel();
      if (view.visible) set(HIDDEN);
    },
  };
}
