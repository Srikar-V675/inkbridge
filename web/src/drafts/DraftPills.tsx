// One Accept/Reject pill per draft in view, at its top-right corner (INK-200, decision 0115).
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { followScroll } from "../chunks/followScroll";
import type { View } from "../chunks/chunks";
import { createGate } from "../lib/changeGate";
import { Button } from "../ui/Button";
import { draftBox } from "./draftView";
import { pillPosition } from "./draftPills";
import type { PlacedOp } from "./draftStore";

export function DraftPills({
  api,
  ops,
  busy,
  onAccept,
  onReject,
}: {
  api: ExcalidrawImperativeAPI;
  ops: PlacedOp[];
  busy: boolean;
  onAccept: (o: PlacedOp) => void;
  onReject: (o: PlacedOp) => void;
}) {
  const [, setView] = useState<View>(() => {
    const s = api.getAppState();
    return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value };
  });
  const [, setTick] = useState(0);
  useEffect(() => followScroll(api, true, setView), [api]);
  // A dragged draft moves its pill on the next scene change.
  useEffect(() => {
    const same = createGate();
    return api.onChange((els, appState) => {
      if (same(els, appState.selectedElementIds)) return;
      setTick((t) => t + 1);
    });
  }, [api]);

  const s = api.getAppState();
  const raw = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui-scale"));
  const k = Number.isFinite(raw) && raw > 0 ? raw : 1;
  const v = { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, width: s.width, height: s.height };
  const size = { width: 232 * k, height: 52 * k };
  const ins = { top: 72 * k, right: 8 * k, bottom: 88 * k, left: 80 * k };
  const els = api.getSceneElements() as never;
  return (
    <>
      {ops.map((o) => {
        const box = draftBox(els, o.id);
        const pos = box && pillPosition(box, v, size, 6, ins);
        if (!pos) return null;
        return (
          <div key={o.id} className="ink-draft-pill" style={{ left: pos.left, top: pos.top }} role="group" aria-label="Draft actions">
            <Button disabled={busy} onClick={() => onAccept(o)}>
              Accept
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => onReject(o)}>
              Reject
            </Button>
          </div>
        );
      })}
    </>
  );
}
