// Agent-colour outline on the ink a thread is about, while the thread is open (INK-134, mirrors drafts/Tether).
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { followScroll } from "../chunks/followScroll";
import { toScreen, type View } from "../chunks/chunks";
import { GlowBox } from "../ui/Badge";

export function AnchorGlow({ api, ids }: { api: ExcalidrawImperativeAPI; ids: string[] }) {
  const [view, setView] = useState<View>(() => {
    const s = api.getAppState();
    return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value };
  });
  useEffect(() => followScroll(api, true, setView), [api]);
  const want = new Set(ids);
  const els = api.getSceneElements().filter((e) => want.has(e.id) && !e.isDeleted);
  if (!els.length) return null;
  const x1 = Math.min(...els.map((e) => e.x));
  const y1 = Math.min(...els.map((e) => e.y));
  const x2 = Math.max(...els.map((e) => e.x + e.width));
  const y2 = Math.max(...els.map((e) => e.y + e.height));
  return <GlowBox rect={toScreen({ x: x1, y: y1, width: x2 - x1, height: y2 - y1 }, view)} />;
}
