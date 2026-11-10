// Where a draft's Accept/Reject pill sits (INK-200, decision 0115). Pure, no Excalidraw import.
import type { Box, Viewport } from "./draftView.ts";
import { inView } from "./draftView.ts";

export interface PillSize { width: number; height: number }
export interface Insets { top: number; right: number; bottom: number; left: number }
export interface PillPos { left: number; top: number }

/** Screen position of a draft's Accept/Reject pill, or null when the draft is off screen
 *  (the "New draft" chip and Jump cover that case). Anchored above the draft's top-right corner;
 *  flips below the bottom edge when there is no room above; then clamped inside the free area
 *  (insets keep it clear of the top bar, rail and tray). */
export function pillPosition(box: Box, v: Viewport, size: PillSize, gap: number, ins: Insets): PillPos | null {
  if (!inView(box, v)) return null;
  const right = (box.x + box.width + v.scrollX) * v.zoom;
  const top = (box.y + v.scrollY) * v.zoom;
  const bottom = (box.y + box.height + v.scrollY) * v.zoom;
  let y = top - size.height - gap;
  if (y < ins.top) y = bottom + gap;
  const minX = ins.left, maxX = v.width - ins.right - size.width;
  const minY = ins.top, maxY = v.height - ins.bottom - size.height;
  return {
    left: Math.max(minX, Math.min(maxX, right - size.width)),
    top: Math.max(minY, Math.min(maxY, y)),
  };
}

/** Cards show for selected drafts only; the pill carries Accept/Reject for the rest. */
export const cardOpIds = (selected: readonly string[], visibleIds: readonly string[]): Set<string> =>
  new Set(selected.filter((id) => visibleIds.includes(id)));

/** Accept all / Reject all are for two or more drafts. */
export const showBulk = (n: number): boolean => n >= 2;
