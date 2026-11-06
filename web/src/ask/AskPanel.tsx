// Ask AI side panel (INK-049, docs/decisions/0046; rebuilt for v4 in INK-161, docs/decisions/0067). Asking never
// touches the canvas; Keep on canvas goes through the agent op queue as a draft the user accepts in DraftBar.
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { applyQuestionUpdate, askQuestion, focusIds, listQuestions, subscribeQuestions, type Question } from "./ask";
import { AskList } from "./AskList";
import { AskThread } from "./AskThread";
import { groupThreads, replyTarget } from "./threads";
import { Panel } from "../ui/Panel";
import "./ask.css";

function useSelection(api: ExcalidrawImperativeAPI): { ids: string[]; raw: number } {
  const [sel, setSel] = useState({ ids: [] as string[], raw: 0 });
  useEffect(
    () =>
      api.onChange((els, appState) => {
        const chosen = appState.selectedElementIds as Record<string, boolean>;
        const ids = focusIds(els as never, chosen);
        const raw = Object.values(chosen).filter(Boolean).length;
        setSel((p) => (p.raw === raw && p.ids.length === ids.length && p.ids.every((x, i) => x === ids[i]) ? p : { ids, raw }));
      }),
    [api],
  );
  return sel;
}

export default function AskPanel({ api, canvas, open, onClose }: { api: ExcalidrawImperativeAPI; canvas: string; open: boolean; onClose: () => void }) {
  const [qs, setQs] = useState<Question[]>([]);
  // Half-typed text is kept per view ("" is the list, otherwise the thread id), so Back does not discard it.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [kept, setKept] = useState<ReadonlySet<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sel = useSelection(api);

  const refetch = useCallback(
    () => listQuestions(canvas).then((l) => (setQs(l), setError("")), (e: Error) => setError(`Could not load questions (${e.message})`)),
    [canvas],
  );
  // Pushes arrive over the ops socket (INK-104); a null push means it reconnected, so refetch.
  useEffect(() => {
    if (!open) return;
    void refetch();
    return subscribeQuestions((q) => {
      if (!q) void refetch();
      else if (q.document_id === canvas) setQs((l) => applyQuestionUpdate(l, q));
    });
  }, [open, canvas, refetch]);

  const threads = useMemo(() => groupThreads(qs), [qs]);
  const thread = openId ? threads.find((t) => t.id === openId) ?? null : null;
  const viewKey = thread ? thread.id : "";
  const text = drafts[viewKey] ?? "";
  const setText = (t: string) => setDrafts((d) => ({ ...d, [viewKey]: t }));
  const view = (id: string | null) => setOpenId(id);

  const ask = async () => {
    setBusy(true);
    try {
      const created = await askQuestion(canvas, text.trim(), sel.ids, thread ? replyTarget(thread).id : null);
      setDrafts((d) => ({ ...d, [viewKey]: "" }));
      setError("");
      setQs((l) => applyQuestionUpdate(l, created));
      setOpenId(thread ? thread.id : created.id);
    } catch (e) {
      setError(`Could not send the question (${(e as Error).message})`);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  // Outside .ink-shell__canvas, whose z-index 1 traps children below the rail and bar (decision 0066).
  const host = document.querySelector(".ink-shell");
  if (!host) return null;
  return createPortal(
    <Panel className="ink-ask">
      {thread ? (
        <AskThread api={api} canvas={canvas} thread={thread} text={text} setText={setText} busy={busy} error={error} onSend={() => void ask()} onBack={() => view(null)} onClose={onClose} refetch={() => void refetch()} kept={kept} onKept={(id) => setKept((k) => new Set(k).add(id))} />
      ) : (
        <AskList threads={threads} text={text} setText={setText} selected={sel.ids.length} raw={sel.raw} busy={busy} error={error} onSend={() => void ask()} onOpen={view} onClose={onClose} />
      )}
    </Panel>,
    host,
  );
}
