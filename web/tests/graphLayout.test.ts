import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { layerOf, layoutGraph, type GraphIR } from "../src/drafts/graphLayout.ts";

const g = (edges: [string, string][], ids = ["a", "b", "c"]): GraphIR => ({
  nodes: ids.map((id) => ({ id, label: id })),
  edges: edges.map(([from, to]) => ({ from, to })),
});

describe("layerOf", () => {
  it("layers a chain", () => {
    const l = layerOf(g([["a", "b"], ["b", "c"]]));
    assert.deepEqual([l.get("a"), l.get("b"), l.get("c")], [0, 1, 2]);
  });
  it("terminates on a cycle", () => {
    const l = layerOf(g([["a", "b"], ["b", "a"]], ["a", "b"]));
    assert.deepEqual([l.get("a"), l.get("b")], [0, 1]);
  });
  it("puts an isolated node at layer 0", () => {
    assert.equal(layerOf(g([["a", "b"]])).get("c"), 0);
  });
});

describe("layoutGraph", () => {
  const ir: GraphIR = {
    nodes: [
      { id: "a", label: "Start" },
      { id: "b", label: "Left", shape: "diamond" },
      { id: "c", label: "Right", shape: "ellipse" },
      { id: "d", label: "End" },
    ],
    edges: [{ from: "a", to: "b" }, { from: "a", to: "c" }, { from: "b", to: "d", label: "yes" }],
  };
  const sk = layoutGraph(ir, 20) as any[];
  const nodes = sk.filter((e) => e.type !== "arrow");
  const arrows = sk.filter((e) => e.type === "arrow");

  it("makes one skeleton per node and one arrow per edge, bound by id", () => {
    assert.deepEqual(nodes.map((n) => n.customData.node), ["a", "b", "c", "d"]);
    assert.equal(arrows.length, 3);
    const ids = new Set(nodes.map((n) => n.id));
    for (const a of arrows) assert.ok(ids.has(a.start.id) && ids.has(a.end.id));
    assert.equal(arrows[2].start.id, "n:b");
    assert.equal(arrows[2].end.id, "n:d");
  });
  it("does not overlap boxes and shares y within a layer", () => {
    for (const [i, p] of nodes.entries())
      for (const q of nodes.slice(i + 1))
        assert.ok(
          p.x + p.width <= q.x || q.x + q.width <= p.x || p.y + p.height <= q.y || q.y + q.height <= p.y,
          `${p.id} overlaps ${q.id}`,
        );
    assert.equal(nodes[1].y, nodes[2].y);
  });
  it("maps shapes", () => {
    assert.deepEqual(nodes.map((n) => n.type), ["rectangle", "diamond", "ellipse", "rectangle"]);
  });
});
