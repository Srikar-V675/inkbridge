// A dashed line from a draft to the chunk it answers (INK-115). Drawn only when the chunk is known.
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { followScroll } from "../chunks/followScroll";
import { listChunks, toScreen, type Bounds, type Chunk, type View } from "../chunks/chunks";
import { draftBox, hasFlowArrow } from "./draftView";
import type { PlacedOp } from "./draftStore";

type Pt = { x: number; y: number };
const mids = (b: { left: number; top: number; width: number; height: number }): Pt[] => [
  { x: b.left + b.width / 2, y: b.top },
  { x: b.left + b.width, y: b.top + b.height / 2 },
  { x: b.left + b.width / 2, y: b.top + b.height },
  { x: b.left, y: b.top + b.height / 2 },
];

/** Bezier between the closest pair of edge midpoints, leaving each box along its edge's normal. */
function tetherPath(a: ReturnType<typeof toScreen>, b: ReturnType<typeof toScreen>): string {
  const ma = mids(a);
  const mb = mids(b);
  let bi = 0, bj = 0, bd = Infinity;
  for (let i = 0; i < 4; i++)
    for (let j = 0; j < 4; j++) {
      const d = (ma[i].x - mb[j].x) ** 2 + (ma[i].y - mb[j].y) ** 2;
      if (d < bd) [bi, bj, bd] = [i, j, d];
    }
  const p = ma[bi];
  const q = mb[bj];
  const pull = (i: number, pt: Pt): Pt => {
    const k = Math.max(40, Math.hypot(p.x - q.x, p.y - q.y) / 3);
    return [{ x: pt.x, y: pt.y - k }, { x: pt.x + k, y: pt.y }, { x: pt.x, y: pt.y + k }, { x: pt.x - k, y: pt.y }][i];
  };
  const c1 = pull(bi, p);
  const c2 = pull(bj, q);
  return `M ${p.x} ${p.y} C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${q.x} ${q.y}`;
}

export function Tether({ api, documentId, op }: { api: ExcalidrawImperativeAPI; documentId: string; op: PlacedOp }) {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [view, setView] = useState<View>(() => {
    const s = api.getAppState();
    return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value };
  });
  useEffect(() => followScroll(api, true, setView), [api]);
  useEffect(() => {
    let off = false;
    void listChunks(documentId).then((c) => {
      if (off) return;
      setChunks(c);
    });
    return () => {
      off = true;
    };
  }, [documentId, op.id]);

  const chunk = chunks.find((c) => c.id === op.payload.anchor_resolved);
  const elements = api.getSceneElements();
  if (hasFlowArrow(elements, op.id)) return null; // the server drew the arrow (INK-201)
  const box: Bounds | null = draftBox(elements as never, op.id);
  if (!chunk || !box) return null;
  return (
    <svg className="ink-tether" aria-hidden>
      <path
        d={tetherPath(toScreen(chunk.bounds, view), toScreen(box, view))}
        fill="none"
        stroke="var(--color-charcoal)"
        strokeWidth={1.6}
        strokeDasharray="4 5"
        strokeLinecap="round"
      />
    </svg>
  );
}
