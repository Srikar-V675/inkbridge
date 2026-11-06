// Ask panel list view: the question form and earlier threads (INK-161, docs/decisions/0067).
import { useEffect, useMemo, useState } from "react";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { CloseIcon, ScopeIcon, SendIcon } from "./askIcons";
import { canSend, relativeTime, replyTarget, scopeLine, threadLine, threadTitle, type Thread } from "./threads";

export function AskList(props: {
  threads: Thread[]; text: string; setText: (t: string) => void; selected: number; raw: number;
  busy: boolean; error: string; onSend: () => void; onOpen: (id: string) => void; onClose: () => void;
}) {
  const { threads, text, setText, selected, raw, busy, error, onSend, onOpen, onClose } = props;
  const ok = canSend({ text, busy, selected, followUp: false });
  const lines = useMemo(() => threads.map(threadLine), [threads]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);
  return (
    <>
      <div className="ink-ask__head">
        <div className="ink-ask__titlebox"><h2 className="ink-ask__title">Ask</h2></div>
        <IconButton label="Close panel" onClick={onClose}><CloseIcon /></IconButton>
      </div>
      <div className="ink-ask__body">
        <form onSubmit={(e) => { e.preventDefault(); if (ok) onSend(); }}>
          <p className="ink-ask__scope"><ScopeIcon /> <b>{scopeLine(selected, raw)}</b></p>
          <div className="ink-ask__field">
            <label>
              <span className="ink-ask__sr">Your question</span>
              <textarea className="ink-ask__input" rows={3} maxLength={4000} value={text} placeholder="Type a question" onChange={(e) => setText(e.target.value)} />
            </label>
            <IconButton className="ink-ask__send" label="Send question" type="submit" disabled={!ok}><SendIcon /></IconButton>
          </div>
          <p className="ink-ask__hint">To ask about one part, circle it with the lasso first.</p>
          {error && <p className="ink-ask__error">{error}</p>}
        </form>
        <h3 className="ink-ask__earlier">Earlier on this canvas</h3>
        {!threads.length && <p className="ink-ask__note">No questions yet</p>}
        {threads.map((t, i) => {
          const line = lines[i];
          return (
            <Button key={t.id} variant="quiet" className="ink-ask__row" onClick={() => onOpen(t.id)}>
              <span className="ink-ask__row-main">
                <span className="ink-ask__row-title">{threadTitle(t)}</span>
                <span className={`ink-ask__row-line${line.failed ? " ink-ask__row-line--failed" : ""}`}>{line.text}</span>
                <span className="ink-ask__row-time">{relativeTime(replyTarget(t).created_at, now)}</span>
              </span>
            </Button>
          );
        })}
      </div>
    </>
  );
}
