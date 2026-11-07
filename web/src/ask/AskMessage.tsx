// One question and its answer inside a thread (ported from the old AskPanel Item and Chips; INK-049, INK-161).
import { useCallback, useEffect, useRef, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { cancelQuestion, drawDiagram, fileName, keepOnCanvas, mermaidBlock, noteUrl, runnerLine, type Question, type Source } from "./ask";
import { AnswerMarkdown } from "./askMarkdown";
import { liveIds, resolveChunk } from "../chunks/chunks";
import { Button } from "../ui/Button";

const WAIT_HINT_MS = 60_000;

/** The backend never writes the vault, so Add to note only copies. LAN HTTP is not a secure context: fall back to a textarea. */
function copyText(text: string): boolean {
  if (window.isSecureContext && navigator.clipboard) {
    void navigator.clipboard.writeText(text);
    return true;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
  document.body.appendChild(ta);
  ta.select();
  try {
    return document.execCommand("copy");
  } finally {
    ta.remove();
  }
}

function Sources(props: { api: ExcalidrawImperativeAPI; canvas: string; sources: Source[] }) {
  const { api, canvas, sources } = props;
  // "gone" per chunk id, resolved up front for the first 10 chips and lazily on click.
  const [gone, setGone] = useState<Record<string, boolean>>({});
  const found = useRef<Record<string, string[]>>({});
  const resolve = useCallback(
    async (id: string) => {
      const r = await resolveChunk(id, canvas);
      if (r.outcome === "found" || r.outcome === "successor") {
        found.current[id] = liveIds(r.chunk!, api.getSceneElements());
        return true;
      }
      setGone((g) => ({ ...g, [id]: true }));
      return false;
    },
    [api, canvas],
  );
  useEffect(() => {
    sources.filter((s) => s.type === "chunk").slice(0, 10).forEach((s) => void resolve(s.id!));
  }, [sources, resolve]);
  const go = async (id: string) => {
    if (!found.current[id] && !(await resolve(id))) return;
    const els = api.getSceneElements().filter((e) => found.current[id].includes(e.id));
    if (!els.length) return setGone((g) => ({ ...g, [id]: true }));
    api.updateScene({ appState: { selectedElementIds: Object.fromEntries(found.current[id].map((x) => [x, true])) } as never });
    api.scrollToContent(els, { fitToViewport: true, viewportZoomFactor: 0.7, maxZoom: 1, animate: false });
  };
  if (!sources.length) return null;
  const notes = sources.filter((s) => s.type === "note");
  return (
    <div>
      {notes.length > 0 && <p className="ink-ask__sources-note">Used from your vault</p>}
      <div className="ink-ask__sources">
        {sources.map((s, i) =>
          s.type === "note" ? (
            <a key={i} className="ink-ask__pill" href={noteUrl(s.path ?? "")}>{fileName(s.path ?? "")}</a>
          ) : (
            <Button key={i} variant="secondary" className="ink-ask__jump" disabled={gone[s.id!]} onClick={() => void go(s.id!)}>
              {gone[s.id!] ? "gone" : "chunk"}
            </Button>
          ),
        )}
      </div>
    </div>
  );
}

export function AskMessage(props: { api: ExcalidrawImperativeAPI; canvas: string; q: Question; refetch: () => void; kept: boolean; onKept: () => void }) {
  const { api, canvas, q, refetch, kept, onKept } = props;
  const [note, setNote] = useState("");
  const [old, setOld] = useState(false);
  useEffect(() => {
    if (q.status !== "pending") return;
    const t = setTimeout(() => setOld(true), Math.max(0, Date.parse(q.created_at) + WAIT_HINT_MS - Date.now()));
    return () => clearTimeout(t);
  }, [q.status, q.created_at]);
  const line = runnerLine(q);
  const cancel = () => cancelQuestion(q.id).then(refetch, (e: Error) => (e.message === "409" ? refetch() : setNote(`Cancel failed (${e.message})`)));
  const keep = async () => {
    setNote("Adding draft...");
    const r = await keepOnCanvas(q, canvas);
    if (r.ok) onKept();
    setNote(r.ok ? "Draft added, accept it on the canvas" : `Could not add draft (${r.reason})`);
  };
  const diagram = async () => {
    setNote("Adding diagram...");
    const r = await drawDiagram(q, canvas);
    setNote(r.ok ? "Diagram added, accept it on the canvas" : `Could not add diagram (${r.reason})`);
  };
  const addToNote = () => {
    const names = q.sources.filter((s) => s.type === "note").map((s) => fileName(s.path ?? ""));
    const text = `${q.answer_md ?? ""}${names.length ? `\n\nSources: ${names.join(", ")}` : ""}`;
    setNote(copyText(text) ? "Copied, paste it into your note" : "Could not copy");
  };
  return (
    <div className="ink-ask__msg">
      <section>
        <p className="ink-ask__label">You</p>
        <p className="ink-ask__text">{q.text}</p>
      </section>
      <section>
        <p className="ink-ask__label"><span className="ink-ask__dot" />Agent</p>
        {q.status === "pending" && (
          <>
            {line ? (
              <p className={q.runner_status === "failed" ? "ink-ask__error" : "ink-ask__note"}>{line}</p>
            ) : (
              <p className="ink-ask__note">{old ? "Waiting for an agent: ask your MCP client to run list_questions" : "Waiting for an agent"}</p>
            )}
            <div className="ink-ask__actions">
              <Button variant="quiet" onClick={() => void cancel()}>Cancel</Button>
            </div>
          </>
        )}
        {q.status === "answered" && q.answer_md && (
          <>
            <div className="ink-ask__answer"><AnswerMarkdown source={q.answer_md} /></div>
            <Sources api={api} canvas={canvas} sources={q.sources} />
            <div className="ink-ask__actions">
              <Button variant="secondary" disabled={kept} onClick={() => void keep()}>Keep on canvas</Button>
              {mermaidBlock(q.answer_md) && <Button variant="secondary" onClick={() => void diagram()}>Draw as diagram</Button>}
              <Button variant="secondary" onClick={addToNote}>Add to note</Button>
            </div>
          </>
        )}
        {q.status === "cancelled" && <p className="ink-ask__note">Cancelled</p>}
        {note && <p className="ink-ask__note">{note}</p>}
      </section>
    </div>
  );
}
