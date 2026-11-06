// URL contract shared with vault notes: /?canvas=<document id>&chunk=<chunk id>
export interface Route {
  canvas: string;
  chunk: string | null;
}

export function readRoute(search: string = window.location.search): Route {
  const p = new URLSearchParams(search);
  return { canvas: p.get("canvas") || "default", chunk: p.get("chunk") };
}

/** Where the page is (INK-118): home, or one canvas with an optional chunk deep link. */
export type Location = { kind: "home"; archived: boolean } | { kind: "canvas"; canvas: string; chunk: string | null };

export function parseLocation(search: string): Location {
  const p = new URLSearchParams(search);
  const canvas = p.get("canvas");
  return canvas ? { kind: "canvas", canvas, chunk: p.get("chunk") } : { kind: "home", archived: p.get("view") === "archived" };
}

/** Remount key: another canvas, or another chunk link in the same canvas (the jump must be applied). */
export function canvasKey(l: Extract<Location, { kind: "canvas" }>): string {
  return `${l.canvas}\n${l.chunk ?? ""}`;
}
