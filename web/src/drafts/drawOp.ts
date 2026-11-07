// Browser-only: convert a pending op and measure it (tech ref 9.9, INK-115).
import { convertToExcalidrawElements } from "@excalidraw/excalidraw";
import { timed } from "../lib/timing";
import { layoutGraph, type GraphIR } from "./graphLayout";
import { measureDrafts, opFontSize, wrapText, type DraftElement, type PendingOp } from "./drafts";

type Skeleton = Parameters<typeof convertToExcalidrawElements>[0];

async function skeletonFor(op: PendingOp, fontSize: number): Promise<Skeleton> {
  if (op.op_type === "write_text") {
    return [{ type: "text", x: 0, y: 0, text: wrapText(op.payload.text ?? "", op.payload.wrap_chars), fontSize }] as Skeleton;
  }
  const source = op.payload.source ?? op.payload.mermaid ?? ""; // mermaid: ops queued before INK-140
  if (op.payload.source_kind === "graph") {
    let graph: GraphIR;
    try {
      graph = JSON.parse(source);
    } catch {
      throw new Error("The graph source is not valid JSON");
    }
    return layoutGraph(graph, fontSize) as Skeleton;
  }
  // Mermaid conversion only runs in the browser; load it on first use.
  const { parseMermaidToExcalidraw } = await import("@excalidraw/mermaid-to-excalidraw");
  let parsed: Awaited<ReturnType<typeof parseMermaidToExcalidraw>>;
  try {
    parsed = await parseMermaidToExcalidraw(source, {
      themeVariables: { fontSize: `${fontSize}px` },
    });
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
 * Convert the op and measure it (INK-115). Touches neither the scene nor the save path: the
 * server places the measured elements and the draft store puts them on the canvas.
 */
export function measureOp(op: PendingOp): Promise<{ elements: DraftElement[]; width: number; height: number }> {
  return timed("ops.measure", () => measure(op), (m) => ({ elements: m?.elements.length ?? 0 }));
}

async function measure(op: PendingOp) {
  const fontSize = opFontSize(op.payload);
  const skeleton = await skeletonFor(op, fontSize);
  // Text boxes are measured at conversion; measuring before the hand-drawn font has loaded makes
  // them too narrow and clips the text.
  await document.fonts?.load(`${fontSize}px Excalifont`).catch(() => undefined);
  const converted = convertToExcalidrawElements(skeleton, { regenerateIds: true });
  const m = measureDrafts(converted as never as DraftElement[], op);
  if (!m.elements.length) throw new Error("the op produced no elements");
  return m;
}
