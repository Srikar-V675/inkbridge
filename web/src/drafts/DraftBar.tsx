// Accept / Reject for agent drafts (INK-045, docs/decisions/0026). Plain DOM over the canvas; the
// ordering rules (save before accept, PATCH before sweep on reject) live in resolve.ts.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { draftBox, inView, panTarget, type Unseen } from "./draftView";
import type { DraftElement } from "./drafts";
import { draftCard, failureText, jumpTarget, trayLabel, verdictToast } from "./draftUi";
import { applyVerdict, draftOpId, draftOps, fetchAppliedOps, patchOp, retryAccept, type Verdict } from "./resolve";
import type { SceneSync } from "../sync/sceneSync";
import { Badge, DraftDot } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Toast } from "../ui/Toast";
import "./DraftBar.css";

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
          const opId = draftOpId(e);
          if (opId !== null && sel.has(e.id)) ops.add(opId);
        }
        const next = [...ops].sort();
        setSelected((prev) => (prev.length === next.length && prev.every((x, i) => x === next[i]) ? prev : next));
      }),
    [api],
  );
  const live = new Set(drafts.map((d) => d.opId));
  return selected.filter((id) => live.has(id));
}

export function DraftBar({
  api,
  sync,
  documentId,
  unseen,
}: {
  api: ExcalidrawImperativeAPI;
  sync: Sync;
  documentId: string;
  unseen: Unseen;
}) {
  const drafts = useDraftOps(api);
  const selected = useSelectedOps(api, drafts);
  const unseenIds = useSyncExternalStore(unseen.subscribe, unseen.ids);
  const unseenCount = unseenIds.length;
  // Accepted or rejected drafts leave the chip. Read from the scene, not the drafts state, which can
  // lag behind a draft that was just added and marked unseen.
  useEffect(() => {
    const live = new Set(draftOps(api.getSceneElements() as never).map((d) => d.opId));
    unseen.prune(live);
  }, [drafts, api, unseen]);
  // A draft the user brings into view by hand stops being unseen. Only listens while there is one.
  useEffect(() => {
    if (unseenCount === 0) return;
    return api.onChange(() => {
      const s = api.getAppState();
      const view = { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, width: s.width, height: s.height };
      const els = api.getSceneElements() as never;
      for (const id of unseen.ids()) {
        const box = draftBox(els, id);
        if (!box || inView(box, view)) unseen.remove(id);
      }
    });
  }, [api, unseen, unseenCount]);
  // Pans to the oldest unseen draft, else the first draft, at the current zoom (never changes it),
  // then clears it from the unseen list.
  const jump = () => {
    const els = api.getSceneElements() as never;
    const id = jumpTarget(unseen.ids(), drafts, (opId) => draftBox(els, opId) !== null);
    if (id === null) return;
    const box = draftBox(els, id);
    if (box) {
      const s = api.getAppState();
      const t = panTarget(box, { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, width: s.width, height: s.height });
      api.updateScene({ appState: { scrollX: t.scrollX, scrollY: t.scrollY }, captureUpdate: CaptureUpdateAction.NEVER });
    }
    unseen.remove(id);
  };
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  // Ops whose accept failed to save or to PATCH: the scene is already accepted locally, so no draft UI can retry them.
  const [retryIds, setRetryIds] = useState<string[]>([]);

  // Success feedback after a verdict; the key makes a new toast restart its timer.
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);

  // Flush the autosave; true only if the scene settled on the server (the accept must not PATCH before this).
  const save = async () => {
    const s = sync.current;
    if (!s) return false;
    await s.flushNow();
    return s.settledVersion() !== null;
  };

  const retry = async () => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const summary = await retryAccept(retryIds, patchOp, save);
      setRetryIds(summary.retry);
      setMessage(failureText(summary));
      const t = verdictToast("accepted", summary);
      if (t) setToast({ id: Date.now(), text: t });
    } finally {
      setBusy(false);
    }
  };

  const run = async (opIds: string[], verdict: Verdict) => {
    const s = sync.current;
    if (!s || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const summary = await applyVerdict(opIds, verdict, {
        scene: () => api.getSceneElementsIncludingDeleted() as unknown as DraftElement[],
        setScene: (els) => {
          api.updateScene({ elements: els as never, captureUpdate: CaptureUpdateAction.NEVER });
          s.notify(els as never);
        },
        save,
        patch: patchOp,
        appliedOps: () => fetchAppliedOps(documentId),
      });
      if (verdict === "accepted") setRetryIds((prev) => [...new Set([...prev.filter((id) => !summary.done.includes(id)), ...summary.retry])]);
      setMessage(failureText(summary));
      const t = verdictToast(verdict, summary);
      if (t) setToast({ id: Date.now(), text: t });
    } finally {
      setBusy(false);
    }
  };

  // The card for each selected draft: kind and a text preview, read from the scene when the selection changes.
  const cards = useMemo(() => {
    void drafts; // a changed draft signature re-reads the text
    const els = api.getSceneElementsIncludingDeleted() as never as DraftElement[];
    return selected.map((opId) => ({ opId, ...draftCard(els, opId) }));
  }, [api, selected, drafts]);

  if (drafts.length === 0 && !message && retryIds.length === 0 && !toast) return null;
  const all = drafts.map((d) => d.opId);
  return (
    <div className="ink-drafts">
      <div className="ink-drafts__stack">
        {message && (
          <div role="status" className="ink-drafts__message">
            {message}
          </div>
        )}
        {retryIds.length > 0 && (
          <Button variant="secondary" disabled={busy} onClick={() => void retry()}>
            Retry accept ({retryIds.length})
          </Button>
        )}
        {cards.map(({ opId, kind, preview }) => (
          <Card key={opId} className="ink-draft-card">
            <div className="ink-draft-card__head">
              <Badge />
              <span>{kind === "text" ? "Text from the agent" : "Diagram from the agent"}</span>
            </div>
            {preview && <p className="ink-draft-card__text">{preview}</p>}
            <div className="ink-draft-card__actions">
              <Button disabled={busy} onClick={() => void run([opId], "accepted")}>
                Accept
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => void run([opId], "rejected")}>
                Reject
              </Button>
            </div>
          </Card>
        ))}
        {unseenCount > 0 && <Chip onClick={jump}>New draft{unseenCount > 1 ? ` (${unseenCount})` : ""}</Chip>}
        {toast && <Toast key={toast.id} message={toast.text} onDismiss={dismissToast} />}
        {drafts.length > 0 && (
          <div role="region" aria-label="Drafts" className="ink-draft-tray">
            <DraftDot />
            <span className="ink-draft-tray__count">{trayLabel(drafts.length)}</span>
            <Button variant="quiet" onClick={jump}>
              Jump
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(all, "accepted")}>
              Accept all
            </Button>
            <Button variant="quiet" disabled={busy} onClick={() => void run(all, "rejected")}>
              Reject all
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
