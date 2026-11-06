/** The canvas title from GET /documents, or the canvas id; never throws. INK-118 owns a proper list. */
export async function fetchTitle(canvas: string): Promise<string> {
  try {
    const r = await fetch("/documents");
    if (!r.ok) return canvas;
    const list: unknown = await r.json();
    if (!Array.isArray(list)) return canvas;
    const hit = list.find((d) => d && d.id === canvas);
    return typeof hit?.title === "string" && hit.title ? hit.title : canvas;
  } catch {
    return canvas;
  }
}
