// URL contract shared with vault notes: /?canvas=<document id>&chunk=<chunk id>
export interface Route {
  canvas: string;
  chunk: string | null;
}

export function readRoute(search: string = window.location.search): Route {
  const p = new URLSearchParams(search);
  return { canvas: p.get("canvas") || "default", chunk: p.get("chunk") };
}
