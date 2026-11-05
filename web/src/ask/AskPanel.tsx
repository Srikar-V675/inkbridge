// Ask AI side panel (INK-049, docs/decisions/0046). Asking never touches the canvas; Keep on canvas
// goes through the agent op queue as a draft the user accepts in DraftBar.
import { useCallback, useEffect, useRef, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { askQuestion, cancelQuestion, fileName, focusIds, keepOnCanvas, listQuestions, MAX_FOCUS, type Question, type Source } from "./ask";
import { AnswerMarkdown } from "./askMarkdown";
import { liveIds, resolveChunk } from "../chunks/chunks";

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
const POLL_MS = 3000;
const WAIT_HINT_MS = 60_000;

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

function Chips(props: { api: ExcalidrawImperativeAPI; canvas: string; sources: Source[] }) {
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
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
      {sources.map((s, i) =>
        s.type === "note" ? (
          <span key={i} style={{ ...btn, cursor: "default" }}>{fileName(s.path ?? "")}</span>
        ) : (
          <button key={i} style={{ ...btn, opacity: gone[s.id!] ? 0.5 : 1 }} disabled={gone[s.id!]} onClick={() => void go(s.id!)}>
            {gone[s.id!] ? "gone" : "chunk"}
          </button>
        ),
      )}
    </div>
  );
}

function Item(props: { api: ExcalidrawImperativeAPI; canvas: string; n: number; q: Question; refetch: () => void; onFollow: (q: Question, n: number) => void }) {
  const { api, canvas, n, q, refetch, onFollow } = props;
  const [note, setNote] = useState("");
  const [kept, setKept] = useState(false);
  const [old, setOld] = useState(false);
  useEffect(() => {
    if (q.status !== "pending") return;
    const t = setTimeout(() => setOld(true), Math.max(0, Date.parse(q.created_at) + WAIT_HINT_MS - Date.now()));
    return () => clearTimeout(t);
  }, [q.status, q.created_at]);
  const cancel = () => cancelQuestion(q.id).then(refetch, (e: Error) => (e.message === "409" ? refetch() : setNote(`Cancel failed (${e.message})`)));
  const keep = async () => {
    setNote("Adding draft...");
    const r = await keepOnCanvas(q, canvas);
    setKept(r.ok);
    setNote(r.ok ? "Draft added, accept it on the canvas" : `Could not add draft (${r.reason})`);
  };
  return (
    <div style={{ borderTop: "1px solid #ddd", padding: "6px 0" }}>
      <div><b>#{n}</b> {q.text} <i style={{ color: "#666" }}>[{q.status}]</i></div>
      {q.status === "pending" && (
        <div>
          <button style={btn} onClick={() => void cancel()}>Cancel</button>
          {old && <div style={{ color: "#666" }}>Waiting for an agent: ask your MCP client to run list_questions</div>}
        </div>
      )}
      {q.status === "answered" && q.answer_md && (
        <>
          <AnswerMarkdown source={q.answer_md} />
          <Chips api={api} canvas={canvas} sources={q.sources} />
          <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
            <button style={btn} disabled={kept} onClick={() => void keep()}>Keep on canvas</button>
            <button style={btn} onClick={() => onFollow(q, n)}>Follow up</button>
          </div>
        </>
      )}
      {note && <div style={{ color: "#666" }}>{note}</div>}
    </div>
  );
}

export default function AskPanel({ api, canvas }: { api: ExcalidrawImperativeAPI; canvas: string }) {
  const [open, setOpen] = useState(false);
  const [qs, setQs] = useState<Question[]>([]);
  const [text, setText] = useState("");
  const [parent, setParent] = useState<{ id: string; n: number } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sel = useSelection(api);

  const refetch = useCallback(
    () => listQuestions(canvas).then((l) => (setQs(l), setError("")), (e: Error) => setError(`Could not load questions (${e.message})`)),
    [canvas],
  );
  const pending = qs.some((q) => q.status === "pending");
  useEffect(() => {
    if (!open) return;
    void refetch();
    if (!pending) return;
    const t = setInterval(() => void refetch(), POLL_MS);
    return () => clearInterval(t);
  }, [open, pending, refetch]);

  const ask = async () => {
    setBusy(true);
    try {
      await askQuestion(canvas, text.trim(), sel.ids, parent?.id);
      setText("");
      setParent(null);
      setError("");
      await refetch();
    } catch (e) {
      setError(`Could not send the question (${(e as Error).message})`);
    } finally {
      setBusy(false);
    }
  };

  const wrap = { position: "absolute", top: 60, right: 12, zIndex: 10, pointerEvents: "none", font: "12px system-ui, sans-serif", color: "#202124" } as const;
  if (!open) return <div style={wrap}><button style={btn} onClick={() => setOpen(true)}>Ask AI</button></div>;
  const ordered = [...qs].reverse();
  return (
    <div style={{ ...wrap, width: "min(360px, calc(100% - 24px))", maxHeight: "70dvh", overflow: "auto", background: "#fff", border: "1px solid #bbb", borderRadius: 6, padding: 8, pointerEvents: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <b>Ask AI</b>
        <button style={btn} onClick={() => setOpen(false)}>Close</button>
      </div>
      <textarea value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} placeholder="Select the doubt on the canvas, then ask" style={{ width: "100%", boxSizing: "border-box", marginTop: 6, font: "inherit" }} />
      {parent && <div>Follow up on #{parent.n} <button style={btn} onClick={() => setParent(null)}>Clear</button></div>}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button style={btn} disabled={busy || !text.trim() || !sel.ids.length} onClick={() => void ask()}>Ask</button>
        <span style={{ color: "#666" }}>
          {sel.ids.length ? `${sel.ids.length} elements${sel.raw > MAX_FOCUS ? ", capped at 200" : ""}` : "Select the doubt first"}
        </span>
      </div>
      {error && <div style={{ color: "#b3261e" }}>{error}</div>}
      {ordered.map((q, i) => (
        <Item key={q.id} api={api} canvas={canvas} n={qs.length - i} q={q} refetch={() => void refetch()} onFollow={(x, n) => setParent({ id: x.id, n })} />
      ))}
    </div>
  );
}
