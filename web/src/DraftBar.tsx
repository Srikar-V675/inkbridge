// Accept / Reject for agent drafts (INK-045, docs/decisions/0026). Plain DOM over the canvas; the
// ordering rules (save before accept, PATCH before sweep on reject) live in resolve.ts.
import { useEffect, useRef, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { DraftElement } from "./drafts";
import { applyVerdict, draftOps, patchOp, type Verdict } from "./resolve";
import type { SceneSync } from "./sceneSync";

type Sync = { current: SceneSync | null };

/** Draft ops in the scene, recomputed only when their signature changes (not on every stroke point). */
function useDraftOps(api: ExcalidrawImperativeAPI): { opId: string; count: number }[] {
  const [ops, setOps] = useState<{ opId: string; count: number }[]>([]);
  const sig = useRef("");
  useEffect(() => {
    const update = (els: readonly unknown[]) => {
      const next = draftOps(els as DraftElement[]);
      const s = next.map((o) => `${o.opId}:${o.count}`).join("|");
      if (s === sig.current) return;
      sig.current = s;
      setOps(next);
    };
    update(api.getSceneElementsIncludingDeleted());
    return api.onChange((els) => update(els));
  }, [api]);
  return ops;
}

function useSelectedOps(api: ExcalidrawImperativeAPI, drafts: { opId: string }[]): string[] {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(
    () =>
      api.onChange((els, appState) => {
        const sel = new Set(Object.keys(appState.selectedElementIds).filter((id) => appState.selectedElementIds[id]));
        const ops = new Set<string>();
        for (const e of els as readonly DraftElement[]) {
          const opId = e.customData?.op_id;
          if (sel.has(e.id) && !e.isDeleted && e.customData?.draft && typeof opId === "string" && e.id.startsWith(`${opId}:`))
            ops.add(opId);
        }
        const next = [...ops].sort();
        setSelected((prev) => (prev.length === next.length && prev.every((x, i) => x === next[i]) ? prev : next));
      }),
    [api],
  );
  const live = new Set(drafts.map((d) => d.opId));
  return selected.filter((id) => live.has(id));
}

const btn = {
  font: "12px system-ui, sans-serif",
  padding: "3px 10px",
  borderRadius: 4,
  border: "1px solid #bbb",
  background: "#fff",
  color: "#202124",
  cursor: "pointer",
  pointerEvents: "auto",
} as const;

export function DraftBar({ api, sync }: { api: ExcalidrawImperativeAPI; sync: Sync }) {
  const drafts = useDraftOps(api);
  const selected = useSelectedOps(api, drafts);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const run = async (opIds: string[], verdict: Verdict) => {
    const s = sync.current;
    if (!s || busy || opIds.length === 0) return;
    setBusy(true);
    setMessage("");
    try {
      const summary = await applyVerdict(opIds, verdict, {
        scene: () => api.getSceneElementsIncludingDeleted() as unknown as DraftElement[],
        setScene: (els) => {
          api.updateScene({ elements: els as never });
          s.notify(els as never);
        },
        save: async () => {
          await s.flushNow();
          return s.settledVersion() !== null;
        },
        patch: patchOp,
      });
      // Undo history from before the verdict could bring a draft tag back; drop it.
      if (summary.done.length) api.history.clear();
      if (summary.failed.length) setMessage(summary.failed.map((f) => f.message).join("; "));
    } finally {
      setBusy(false);
    }
  };

  if (drafts.length === 0 && !message) return null;
  const all = drafts.map((d) => d.opId);
  const total = drafts.reduce((n, d) => n + d.count, 0);
  return (
    <div
      style={{
        position: "absolute",
        bottom: 12,
        right: 56,
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 4,
        pointerEvents: "none",
        font: "12px system-ui, sans-serif",
      }}
    >
      {message && (
        <div role="status" style={{ background: "#fff3cd", color: "#202124", padding: "2px 10px", borderRadius: 4 }}>
          {message}
        </div>
      )}
      {drafts.length > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", background: "#fff", padding: 6, borderRadius: 6, boxShadow: "0 1px 4px #0003" }}>
          <span>{drafts.length === 1 ? "1 draft" : `${drafts.length} drafts`} ({total} elements)</span>
          {selected.length > 0 && (
            <>
              <button style={btn} disabled={busy} onClick={() => void run(selected, "accepted")}>Accept</button>
              <button style={btn} disabled={busy} onClick={() => void run(selected, "rejected")}>Reject</button>
            </>
          )}
          <button style={btn} disabled={busy} onClick={() => void run(all, "accepted")}>Accept all</button>
          <button style={btn} disabled={busy} onClick={() => void run(all, "rejected")}>Reject all</button>
        </div>
      )}
    </div>
  );
}
