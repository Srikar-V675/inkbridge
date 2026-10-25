// Browser-only: turn a pending op into draft elements on the live canvas (tech ref 9.9).
import { convertToExcalidrawElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { opElements, toDrafts, type DraftElement, type PendingOp } from "./drafts";

const FONT_SIZE = 20;

type Skeleton = Parameters<typeof convertToExcalidrawElements>[0];

async function skeletonFor(op: PendingOp): Promise<Skeleton> {
  if (op.op_type === "write_text") {
    return [{ type: "text", x: 0, y: 0, text: op.payload.text ?? "" }] as Skeleton;
  }
  // Mermaid conversion only runs in the browser; load it on first use.
  const { parseMermaidToExcalidraw } = await import("@excalidraw/mermaid-to-excalidraw");
  let parsed: Awaited<ReturnType<typeof parseMermaidToExcalidraw>>;
  try {
    parsed = await parseMermaidToExcalidraw(op.payload.mermaid ?? "");
  } catch (e) {
    throw new Error(`Mermaid could not be parsed: ${e instanceof Error ? e.message : String(e)}`);
  }
  // Non-flowchart diagrams come back as a single image: only flowcharts become editable shapes.
  if (parsed.elements.some((e) => e.type === "image")) {
    throw new Error("Only Mermaid flowcharts are supported");
  }
  return parsed.elements as Skeleton;
}

/**
 * Draw the op as dashed drafts (once) and return the ids of its elements on the canvas.
 * `persist` saves the scene with the drafts in it: the caller acks only after that, because an
 * applied op is never replayed, so an unsaved draft lost to a reload would never come back.
 */
export async function drawOp(
  api: ExcalidrawImperativeAPI,
  op: PendingOp,
  persist: (elements: readonly unknown[]) => Promise<void>,
): Promise<string[]> {
  const prefix = op.payload.id_prefix;
  const already = opElements(api.getSceneElementsIncludingDeleted() as never as DraftElement[], prefix);
  if (already.length) return already.map((e) => e.id); // replay of an op drawn before a reload
  const skeleton = await skeletonFor(op);
  // Text boxes are measured at conversion; measuring before the hand-drawn font has loaded makes
  // them too narrow and clips the text.
  await document.fonts?.load(`${FONT_SIZE}px Excalifont`).catch(() => undefined);
  const converted = convertToExcalidrawElements(skeleton, { regenerateIds: true });
  const drafts = toDrafts(converted as never as DraftElement[], op);
  if (!drafts.length) throw new Error("the op produced no elements");
  api.updateScene({ elements: [...api.getSceneElementsIncludingDeleted(), ...drafts] as never });
  await persist(api.getSceneElementsIncludingDeleted());
  return drafts.map((e) => e.id);
}
