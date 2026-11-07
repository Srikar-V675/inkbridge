// Pure layered layout for the graph IR of draw_diagram (INK-140, decision 0100). No Excalidraw import.

export interface GraphIR {
  nodes: { id: string; label: string; shape?: "rect" | "ellipse" | "diamond" }[];
  edges: { from: string; to: string; label?: string }[];
}

/** Longest path from the sources; back edges (found by an iterative DFS) are dropped so cycles end. */
export function layerOf(g: GraphIR): Map<string, number> {
  const out = new Map<string, string[]>(g.nodes.map((n) => [n.id, []]));
  for (const e of g.edges) out.get(e.from)?.push(e.to);
  const state = new Map<string, 1 | 2>(); // 1 = on the DFS stack, 2 = done
  const forward = new Map<string, string[]>(g.nodes.map((n) => [n.id, []]));
  const order: string[] = [];
  for (const root of g.nodes.map((n) => n.id)) {
    if (state.has(root)) continue;
    const stack: [string, number][] = [[root, 0]];
    state.set(root, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const next = out.get(top[0])![top[1]++];
      if (next === undefined) {
        state.set(top[0], 2);
        order.push(top[0]);
        stack.pop();
      } else if (state.get(next) !== 1) {
        forward.get(top[0])!.push(next);
        if (!state.has(next)) {
          state.set(next, 1);
          stack.push([next, 0]);
        }
      }
    }
  }
  const layer = new Map<string, number>(g.nodes.map((n) => [n.id, 0]));
  for (const id of order.reverse()) // reverse post-order is topological over the forward edges
    for (const to of forward.get(id)!) layer.set(to, Math.max(layer.get(to)!, layer.get(id)! + 1));
  return layer;
}

const TYPE = { rect: "rectangle", ellipse: "ellipse", diamond: "diamond" } as const;

/** Skeletons for convertToExcalidrawElements: top-down layers, nodes in source order within one. */
export function layoutGraph(g: GraphIR, fontSize: number): Record<string, unknown>[] {
  const layer = layerOf(g);
  const gap = 2 * fontSize;
  const size = (n: GraphIR["nodes"][number]) => {
    const k = n.shape === "diamond" ? 1.5 : 1;
    return { w: k * Math.max(120, n.label.length * 0.6 * fontSize + 2 * fontSize), h: k * 2.4 * fontSize };
  };
  const rowH = new Map<number, number>();
  for (const n of g.nodes) rowH.set(layer.get(n.id)!, Math.max(rowH.get(layer.get(n.id)!) ?? 0, size(n).h));
  const yOf = new Map<number, number>();
  let y = 0;
  for (const l of [...rowH.keys()].sort((a, b) => a - b)) {
    yOf.set(l, y);
    y += rowH.get(l)! + gap;
  }
  const nextX = new Map<number, number>();
  const box = new Map<string, { x: number; y: number; w: number; h: number }>();
  const nodes = g.nodes.map((n) => {
    const l = layer.get(n.id)!;
    const { w, h } = size(n);
    const x = nextX.get(l) ?? 0;
    nextX.set(l, x + w + gap);
    const top = yOf.get(l)!;
    box.set(n.id, { x, y: top, w, h });
    return {
      type: TYPE[n.shape ?? "rect"],
      id: `n:${n.id}`,
      x,
      y: top,
      width: w,
      height: h,
      label: { text: n.label, fontSize },
      customData: { node: n.id },
    };
  });
  const arrows = g.edges.map((e) => {
    const b = box.get(e.from)!;
    return {
      type: "arrow",
      x: b.x + b.w / 2,
      y: b.y + b.h,
      start: { id: `n:${e.from}` },
      end: { id: `n:${e.to}` },
      ...(e.label ? { label: { text: e.label, fontSize } } : {}),
    };
  });
  return [...nodes, ...arrows];
}
