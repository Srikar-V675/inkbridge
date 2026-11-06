// Text measuring for the properties card (INK-175, docs/decisions/0075). Browser only: it needs a canvas
// and the document font set. Excalidraw loads Nunito and Cascadia lazily, so a family is loaded before
// the first measure.
const FAMILY_CSS: Record<number, string> = { 5: "Excalifont", 6: "Nunito", 3: "Cascadia" };

let ctx: CanvasRenderingContext2D | null = null;

export function measure(line: string, size: number, family: number): number {
  ctx ??= document.createElement("canvas").getContext("2d");
  if (!ctx) return line.length * size * 0.6;
  ctx.font = `${size}px ${FAMILY_CSS[family] ?? "sans-serif"}, sans-serif`;
  return ctx.measureText(line).width;
}

export const loadFont = (family: number, size: number): Promise<void> =>
  document.fonts.load(`${size}px ${FAMILY_CSS[family] ?? "sans-serif"}`).then(() => {}, () => {});
