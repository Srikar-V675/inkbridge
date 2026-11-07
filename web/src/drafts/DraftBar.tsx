// Draft card, tray and toasts (INK-045, INK-115, decision 0090). The server owns the verdicts
// (resolve.ts); Reject waits out the toast so it can be undone, because the server has no unreject.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { draftBox, inView, panTarget, type Unseen } from "./draftView";
import { draftOpId, type DraftElement } from "./drafts";
import { offsetOf, type DraftStore, type PlacedOp } from "./draftStore";
import { draftCard, failureText, jumpTarget, trayLabel, verdictToast } from "./draftUi";
import { accept, fetchDrafts, reject, unaccept } from "./resolve";
import { Tether } from "./Tether";
import { createGate } from "../lib/changeGate";
import { Badge, DraftDot } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Toast } from "../ui/Toast";
import "./DraftBar.css";

function useSelectedOps(api: ExcalidrawImperativeAPI, liveIds: string[]): string[] {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => {
    // A selection change replaces selectedElementIds and an element change replaces the array, so
    // identical refs cannot change the answer (INK-174).
    const same = createGate();
    return api.onChange((els, appState) => {
      if (same(els, appState.selectedElementIds)) return;
      const sel = new Set(Object.keys(appState.selectedElementIds).filter((id) => appState.selectedElementIds[id]));
      const ops = new Set<string>();
      for (const e of els as readonly DraftElement[]) {
        const opId = draftOpId(e);
        if (opId !== null && sel.has(e.id)) ops.add(opId);
      }
      const next = [...ops].sort();
      setSelected((prev) => (prev.length === next.length && prev.every((x, i) => x === next[i]) ? prev : next));
    });
  }, [api]);
  return selected.filter((id) => liveIds.includes(id));
}

type ToastState = { id: number; text: string; undo?: () => void };

export function DraftBar({
  api,
  documentId,
  unseen,
  drafts,
  onOpenThread,
}: {
  api: ExcalidrawImperativeAPI;
  documentId: string;
  unseen: Unseen;
  drafts: DraftStore;
  onOpenThread: (questionId: string | null) => void;
}) {
  const ops = useSyncExternalStore(drafts.subscribe, drafts.list);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const visible = ops.filter((o) => !hidden.has(o.id));
  const selected = useSelectedOps(api, visible.map((o) => o.id));
  const unseenIds = useSyncExternalStore(unseen.subscribe, unseen.ids);
  const unseenCount = unseenIds.length;
  // Accepted or rejected drafts leave the chip.
  useEffect(() => {
    unseen.prune(new Set(ops.map((o) => o.id)));
  }, [ops, unseen]);
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
  // Pans to the oldest unseen draft, else the first draft, at the current zoom (never changes it).
  const jump = () => {
    const els = api.getSceneElements() as never;
    const id = jumpTarget(unseen.ids(), visible.map((o) => ({ opId: o.id })), (opId) => draftBox(els, opId) !== null);
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
  const [toast, setToast] = useState<ToastState | null>(null);
  const refetch = useCallback(() => void fetchDrafts(documentId).then((o) => drafts.set(o)), [documentId, drafts]);

  // Rejects waiting out their toast: nothing is sent until it expires, is replaced or the bar goes away.
  const pending = useRef<string[]>([]);
  const flushRejects = useCallback(async () => {
    const ids = pending.current;
    pending.current = [];
    if (ids.length === 0) return;
    const results = await Promise.all(ids.map((id) => reject(id)));
    setMessage(failureText(results));
    const failed = ids.filter((_, i) => !results[i].ok);
    ids.filter((_, i) => results[i].ok).forEach((id) => drafts.remove(id));
    if (failed.length) setHidden((h) => new Set([...h].filter((id) => !failed.includes(id))));
  }, [drafts]);
  useEffect(() => () => void flushRejects(), [flushRejects]);
  const dismissToast = useCallback(() => {
    void flushRejects();
    setToast(null);
  }, [flushRejects]);
  const show = (text: string, undo?: () => void) => {
    void flushRejects();
    setToast({ id: Date.now(), text, undo });
  };

  const acceptOps = async (list: PlacedOp[]) => {
    if (busy || list.length === 0) return;
    setBusy(true);
    setMessage("");
    try {
      const scene = api.getSceneElementsIncludingDeleted() as never as DraftElement[];
      const results = await Promise.all(
        list.map((o) => {
          const { dx, dy } = offsetOf(scene, o);
          return accept(o.id, dx, dy);
        }),
      );
      setMessage(failureText(results));
      const done = list.filter((_, i) => results[i].ok);
      done.forEach((o) => drafts.remove(o.id));
      const text = verdictToast("accepted", { done });
      if (text) show(text, () => void undoAccept(done.map((o) => o.id)));
    } finally {
      setBusy(false);
    }
  };
  const undoAccept = async (ids: string[]) => {
    setToast(null);
    const results = await Promise.all(ids.map((id) => unaccept(id)));
    setMessage(failureText(results));
    refetch(); // the op is placed again; the reconcile effect redraws the dashed draft
  };
  const rejectOps = (list: PlacedOp[]) => {
    if (list.length === 0) return;
    void flushRejects();
    const ids = list.map((o) => o.id);
    setHidden((h) => new Set([...h, ...ids]));
    show(verdictToast("rejected", { done: ids })!, () => {
      pending.current = [];
      setHidden((h) => new Set([...h].filter((id) => !ids.includes(id))));
      setToast(null);
    });
    pending.current = ids; // show() flushed the previous batch; this one waits for its own toast
  };

  const cardIds = new Set([...selected, ...(visible.length === 1 ? [visible[0].id] : [])]);
  const cards = visible.filter((o) => cardIds.has(o.id));
  if (visible.length === 0 && !message && !toast) return null;
  return (
    <div className="ink-drafts">
      {cards.map((o) => o.payload.anchor_resolved && <Tether key={o.id} api={api} documentId={documentId} op={o} />)}
      <div className="ink-drafts__stack">
        {message && (
          <div role="status" className="ink-drafts__message">
            {message}
          </div>
        )}
        {cards.map((o) => {
          const { kind, preview } = draftCard(o);
          return (
            <Card key={o.id} className="ink-draft-card">
              <div className="ink-draft-card__head">
                <Badge />
                <span>{kind === "text" ? "Text from the agent" : "Diagram from the agent"}</span>
              </div>
              {preview && <p className="ink-draft-card__text">{preview}</p>}
              <div className="ink-draft-card__actions">
                <Button disabled={busy} onClick={() => void acceptOps([o])}>
                  Accept
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => rejectOps([o])}>
                  Reject
                </Button>
                <span className="ink-draft-card__spacer" />
                <Button variant="quiet" onClick={() => onOpenThread(o.payload.question_id ?? null)}>
                  Open thread
                </Button>
              </div>
            </Card>
          );
        })}
        {unseenCount > 0 && <Chip onClick={jump}>New draft{unseenCount > 1 ? ` (${unseenCount})` : ""}</Chip>}
        {toast && (
          <Toast
            key={toast.id}
            message={toast.text}
            actionLabel={toast.undo ? "Undo" : undefined}
            onAction={toast.undo}
            onDismiss={dismissToast}
          />
        )}
        {visible.length > 0 && (
          <div role="region" aria-label="Drafts" className="ink-draft-tray">
            <DraftDot />
            <span className="ink-draft-tray__count">{trayLabel(visible.length)}</span>
            <Button variant="quiet" onClick={jump}>
              Jump
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => void acceptOps(visible)}>
              Accept all
            </Button>
            <Button variant="quiet" disabled={busy} onClick={() => rejectOps(visible)}>
              Reject all
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
