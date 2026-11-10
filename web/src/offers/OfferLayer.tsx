// Offer chips beside their chunks, popovers and Focus (INK-131, decision 0097). The chips live on
// one transformed plane that follows scroll and zoom by writing the style directly, so a pan frame
// costs no React render. UI state only: nothing here touches the Excalidraw scene except selection.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { listChunks, liveIds, type Chunk } from "../chunks/chunks";
import { navigate } from "../lib/nav";
import type { Refresh } from "../sync/chunkRefresh";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import {
  addLinks,
  canvasLink,
  chipLabel,
  dismissOffer,
  linksText,
  listOffers,
  noteRequest,
  obsidianUrl,
  planeStyle,
  popoverKind,
  setFocus,
  tapOffer,
  type Offer,
} from "./offers";
import type { OfferStore } from "./offerStore";
import "./OfferLayer.css";

const str = (v: unknown) => (typeof v === "string" ? v : undefined);

function PopoverBody({ offer, canvas, store, close, onOpenAsk }: { offer: Offer; canvas: string; store: OfferStore; close: () => void; onOpenAsk: (questionId?: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const kind = popoverKind(offer);
  const run = (fn: () => Promise<void>) => fn().then(close, () => setError("That did not work. Try again."));
  const notUseful = (
    <Button variant="quiet" onClick={() => void run(() => dismissOffer(offer.id).then(() => store.remove(offer.id)))}>
      Not useful
    </Button>
  );
  const p = offer.payload;
  const vault = str(p.vault);
  const file = str(p.file);
  const doc = str(p.other_document);
  return (
    <Card className="ink-offer-popover">
      {kind === "answer" ? (
        <>
          <p>Answer ready</p>
          <Button onClick={() => (onOpenAsk(str(p.question_id)), close())}>Open thread</Button>
        </>
      ) : (
        <>
          <p>{offer.reason}</p>
          {kind === "note" && (
            <Button variant="secondary" onClick={() => void run(() => navigator.clipboard.writeText(noteRequest(canvas)))}>
              Copy request
            </Button>
          )}
          {kind === "related" && (
            <>
              {doc && (
                <Button variant="secondary" onClick={() => (navigate(canvasLink(window.location.origin, doc, str(p.other_chunk))), close())}>
                  Jump to canvas
                </Button>
              )}
              {vault && file && (
                <a className="ink-offer-link" href={obsidianUrl(vault, file)}>
                  Open in Obsidian
                </a>
              )}
              {linksText(offer, window.location.origin) && (
                <Button variant="secondary" onClick={() => void run(() => addLinks(offer, window.location.origin))}>
                  Add links beside
                </Button>
              )}
            </>
          )}
        </>
      )}
      {kind !== "answer" && notUseful}
      {error && <p role="alert">{error}</p>}
    </Card>
  );
}

export function OfferLayer(props: { api: ExcalidrawImperativeAPI; canvas: string; store: OfferStore; refresh: Refresh; onOpenAsk: (questionId?: string) => void }) {
  const { api, canvas, store, refresh, onOpenAsk } = props;
  const { offers, focus } = useSyncExternalStore(store.subscribe, store.get);
  const plane = useRef<HTMLDivElement>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const wanted = offers.length > 0 && !focus;

  useEffect(() => {
    const write = (scrollX: number, scrollY: number, zoom: number) => {
      const s = planeStyle({ scrollX, scrollY, zoom });
      plane.current?.style.setProperty("transform", s.transform);
      plane.current?.style.setProperty("--z", s.z);
    };
    const s = api.getAppState();
    write(s.scrollX, s.scrollY, s.zoom.value);
    return api.onScrollChange((x, y, z) => write(x, y, z.value));
  }, [api, wanted]);

  useEffect(() => {
    if (!wanted) return;
    let latest = 0;
    const load = () => {
      const n = ++latest;
      void listChunks(canvas).then((rows) => n === latest && setChunks(rows));
    };
    load();
    const off = refresh.subscribe(load);
    return () => (latest++, off());
  }, [canvas, refresh, wanted]);

  useEffect(() => {
    if (!openId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenId(null);
    const onDown = (e: PointerEvent) => !(e.target as Element | null)?.closest?.(".ink-offer-pin") && setOpenId(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown, true);
    return () => (window.removeEventListener("keydown", onKey), window.removeEventListener("pointerdown", onDown, true));
  }, [openId]);

  const tap = (o: Offer, c: Chunk) => {
    void tapOffer(o.id).catch(() => {}); // a failed tap only loses the "seen" mark
    const ids = liveIds(c, api.getSceneElements() as never);
    if (ids.length) api.updateScene({ appState: { selectedElementIds: Object.fromEntries(ids.map((id) => [id, true])) as never } });
    setOpenId((cur) => (cur === o.id ? null : o.id));
  };

  const byId = new Map(chunks.map((c) => [c.id, c]));
  return (
    <>
      <div className="ink-offer-layer">
        <div ref={plane} className="ink-offer-plane">
          {wanted &&
            offers.map((o) => {
              const c = byId.get(o.anchor_chunk);
              if (!c) return null;
              return (
                <div key={o.id} className="ink-offer-pin" style={{ left: c.bounds.x + c.bounds.width + 12, top: c.bounds.y }}>
                  <Chip onClick={() => tap(o, c)} aria-expanded={openId === o.id}>
                    {chipLabel(o)}
                  </Chip>
                  {openId === o.id && <PopoverBody offer={o} canvas={canvas} store={store} close={() => setOpenId(null)} onOpenAsk={onOpenAsk} />}
                </div>
              );
            })}
        </div>
      </div>
      {focus && <FocusBar store={store} canvas={canvas} />}
    </>
  );
}

const reload = (store: OfferStore, canvas: string) => listOffers(canvas).then((r) => store.set(r.offers, r.waiting, r.focus)).catch(() => {});

function FocusBar({ store, canvas }: { store: OfferStore; canvas: string }) {
  const { waiting } = useSyncExternalStore(store.subscribe, store.get);
  return (
    <Card className="ink-focus-bar">
      <div role="status">
        <span>Focus on. Suggestions wait until you turn it off. Ask still works.</span> <span>{waiting} waiting</span>
      </div>
      <Button variant="secondary" onClick={() => void toggleFocus(store, canvas, false)}>
        Turn off
      </Button>
    </Card>
  );
}

async function toggleFocus(store: OfferStore, canvas: string, on: boolean) {
  try {
    await setFocus(canvas, on);
  } catch {
    return; // the server did not take it: the toggle stays as it was
  }
  store.setFocus(on);
  await reload(store, canvas); // on: the waiting count; off: what was held back
}

export function FocusToggle({ store, canvas }: { store: OfferStore; canvas: string }) {
  const { focus } = useSyncExternalStore(store.subscribe, store.get);
  return (
    <Button variant="quiet" className="ink-focus-toggle" aria-pressed={focus} onClick={() => void toggleFocus(store, canvas, !focus)}>
      {focus ? "Focus on" : "Focus"}
    </Button>
  );
}
