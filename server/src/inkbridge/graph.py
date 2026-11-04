"""In-memory chunk graph (INK-060, decision 0056). Built per request from outline chunks, never stored."""

import re
from typing import Literal

import networkx as nx

Direction = Literal["both", "out", "in"]
PREVIEW = 160
LABEL = 40


def build(chunks: list[dict]) -> nx.DiGraph:
    """Active chunks as nodes, arrow links between two active chunks as edges."""
    g = nx.DiGraph()
    active = {c["id"]: c for c in chunks if c.get("status") == "active"}
    for cid, c in active.items():
        g.add_node(cid, order=c.get("order"), kind=c.get("kind"), text=c.get("text"))
    for cid, c in active.items():
        for link in c.get("links") or []:
            if link["to"] in active and link["to"] != cid:
                g.add_edge(cid, link["to"], kind=link["kind"])
    return g


def _view(g: nx.DiGraph, direction: Direction):
    if direction == "out":
        return g
    if direction == "in":
        return g.reverse(copy=False)
    return g.to_undirected(as_view=True)


def _sort_key(g, cid):  # reading order, unordered last, id as tie-break
    o = g.nodes[cid]["order"]
    return (o is None, o if o is not None else 0, cid)


def _node(g, cid, distance=None) -> dict:
    n = g.nodes[cid]
    text = n["text"]
    out = {
        "id": cid,
        "order": n["order"],
        "kind": n["kind"],
        "text": text if not text or len(text) <= PREVIEW else text[: PREVIEW - 1] + "…",
    }
    if distance is not None:
        out["distance"] = distance
    return out


def _edges(g, shown: set[str], max_edges: int):
    """Edges of g (always in the real arrow direction) between shown nodes, capped."""
    every = sorted((u, v, d["kind"]) for u, v, d in g.edges(data=True) if u in shown and v in shown)
    return [{"from": u, "to": v, "kind": k} for u, v, k in every[:max_edges]], max(
        0, len(every) - max_edges
    )


def subgraph(g, chunk_id, depth=1, direction="both", max_nodes=40, max_edges=80) -> dict:
    dist = nx.single_source_shortest_path_length(_view(g, direction), chunk_id, cutoff=depth)
    ordered = sorted(dist, key=lambda c: (dist[c], _sort_key(g, c)))
    shown_ids = ordered[:max_nodes]
    edges, omitted_edges = _edges(g, set(shown_ids), max_edges)
    return {
        "center": chunk_id,
        "depth": depth,
        "direction": direction,
        "nodes": [_node(g, c, dist[c]) for c in shown_ids],
        "edges": edges,
        "reachable": len(dist),
        "omitted_nodes": len(dist) - len(shown_ids),
        "omitted_edges": omitted_edges,
    }


def path(g, source, target, direction="both", max_nodes=100) -> dict:
    view = _view(g, direction)
    try:
        ids = nx.shortest_path(view, source, target)
    except nx.NetworkXNoPath:
        return {
            "from": source,
            "to": target,
            "direction": direction,
            "found": False,
            "length": None,
            "nodes": [],
            "edges": [],
            "omitted_nodes": 0,
        }
    shown = ids[:max_nodes]
    edges, _ = _edges(g, set(shown), max_nodes)
    return {
        "from": source,
        "to": target,
        "direction": direction,
        "found": True,
        "length": len(ids) - 1,
        "nodes": [_node(g, c) for c in shown],
        "edges": edges,
        "omitted_nodes": len(ids) - len(shown),
    }


def components(g, max_components=30, max_ids=20) -> dict:
    comps = sorted(
        nx.connected_components(g.to_undirected(as_view=True)),
        key=lambda s: (-len(s), min(_sort_key(g, c) for c in s)),
    )
    out = []
    for comp in comps[:max_components]:
        ids = sorted(comp, key=lambda c: _sort_key(g, c))
        out.append(
            {
                "size": len(ids),
                "chunk_ids": ids[:max_ids],
                "omitted_ids": max(0, len(ids) - max_ids),
            }
        )
    return {
        "chunk_count": g.number_of_nodes(),
        "component_count": len(comps),
        "isolated": sum(1 for c in comps if len(c) == 1),
        "components": out,
        "omitted_components": max(0, len(comps) - max_components),
    }


_UNSAFE = re.compile(r"[\"\[\](){}<>|;#&`\\]")


def mermaid(nodes: list[dict], edges: list[dict]) -> str:
    """`flowchart TD` text for shown nodes and edges. Node ids are n1..nN, not chunk ids."""
    alias = {n["id"]: f"n{i}" for i, n in enumerate(nodes, 1)}
    lines = ["flowchart TD"]
    for n in nodes:
        label = " ".join(_UNSAFE.sub("", n.get("text") or n.get("kind") or "chunk").split())
        label = label[:LABEL] or "chunk"
        lines.append(f'  {alias[n["id"]]}["{label}"]')
    lines += [
        f"  {alias[e['from']]} --> {alias[e['to']]}"
        for e in edges
        if e["from"] in alias and e["to"] in alias
    ]
    return "\n".join(lines)
