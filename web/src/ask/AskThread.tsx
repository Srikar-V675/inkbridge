// Ask panel thread view: one question, its follow-ups and the follow-up field (INK-161, docs/decisions/0067).
import { useEffect, useRef } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { AskMessage } from "./AskMessage";
import { BackIcon, CloseIcon } from "./askIcons";
import { canSend, messageCount, threadTitle, type Thread } from "./threads";

export function AskThread(props: {
  api: ExcalidrawImperativeAPI; canvas: string; thread: Thread; text: string; setText: (t: string) => void;
  busy: boolean; error: string; onSend: () => void; onBack: () => void; onClose: () => void; refetch: () => void;
  kept: ReadonlySet<string>; onKept: (id: string) => void;
}) {
  const { api, canvas, thread, text, setText, busy, error, onSend, onBack, onClose, refetch, kept, onKept } = props;
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = body.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread.items.length]);
  const ok = canSend({ text, busy, selected: 0, followUp: true });
  return (
    <>
      <div className="ink-ask__head">
        <div className="ink-ask__titlebox">
          <Button variant="quiet" className="ink-ask__back" aria-label="Back to earlier questions" onClick={onBack}><BackIcon />All threads</Button>
          <h2 className="ink-ask__title">{threadTitle(thread)}</h2>
          <p className="ink-ask__meta">{messageCount(thread)} messages</p>
        </div>
        <IconButton label="Close panel" onClick={onClose}><CloseIcon /></IconButton>
      </div>
      <div ref={body} className="ink-ask__body ink-ask__thread">
        {thread.items.map((q) => (
          <AskMessage key={q.id} api={api} canvas={canvas} q={q} refetch={refetch} kept={kept.has(q.id)} onKept={() => onKept(q.id)} />
        ))}
      </div>
      {error && <p className="ink-ask__error">{error}</p>}
      <form className="ink-ask__form" onSubmit={(e) => { e.preventDefault(); if (ok) onSend(); }}>
        <label>
          <span className="ink-ask__sr">Follow-up question</span>
          <textarea className="ink-ask__follow" rows={2} maxLength={4000} value={text} placeholder="Ask a follow-up, or write it on the canvas" onChange={(e) => setText(e.target.value)} />
        </label>
        <Button variant="primary" type="submit" disabled={!ok}>Send</Button>
      </form>
    </>
  );
}
