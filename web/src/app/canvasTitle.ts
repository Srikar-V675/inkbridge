/** The canvas title from GET /documents/{id} (archived canvases too), or the canvas id; never throws. */
export async function fetchTitle(canvas: string): Promise<string> {
  try {
    const r = await fetch(`/documents/${encodeURIComponent(canvas)}`);
    if (!r.ok) return canvas;
    const doc: unknown = await r.json();
    const title = (doc as { title?: unknown } | null)?.title;
    return typeof title === "string" && title ? title : canvas;
  } catch {
    return canvas;
  }
}
