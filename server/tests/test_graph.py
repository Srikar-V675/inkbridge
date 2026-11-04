"""INK-060: the in-memory chunk graph, on plain dicts shaped like chunk_outline chunks."""

import re
from itertools import pairwise

from inkbridge import graph, mermaid


def ch(i, links=(), status="active", order=None, text=None, kind="handwriting"):
    return {
        "id": i, "order": order, "kind": kind, "text": text, "status": status,
        "links": [{"to": t, "kind": "arrow"} for t in links],
    }  # fmt: skip


def chain(*ids):
    return [ch(a, [b]) for a, b in pairwise(ids)] + [ch(ids[-1])]


def ids(r):
    return [n["id"] for n in r["nodes"]]


def test_subgraph_depth_limits_reach():
    g = graph.build(chain("a", "b", "c", "d"))
    r = graph.subgraph(g, "a", depth=2)
    assert ids(r) == ["a", "b", "c"] and r["omitted_nodes"] == 0
    assert [n["distance"] for n in r["nodes"]] == [0, 1, 2]


def test_direction_out_in_both():
    g = graph.build(chain("a", "b", "c"))
    assert sorted(ids(graph.subgraph(g, "b", direction="out"))) == ["b", "c"]
    assert sorted(ids(graph.subgraph(g, "b", direction="in"))) == ["a", "b"]
    assert sorted(ids(graph.subgraph(g, "b", direction="both"))) == ["a", "b", "c"]


def test_node_cap_counts_omitted():
    leaves = [f"l{i}" for i in range(10)]
    g = graph.build([ch("hub", leaves)] + [ch(leaf) for leaf in leaves])
    r = graph.subgraph(g, "hub", max_nodes=4)
    assert len(r["nodes"]) == 4 and r["omitted_nodes"] == 7
    shown = set(ids(r))
    assert all(e["from"] in shown and e["to"] in shown for e in r["edges"])
    assert len(r["edges"]) == 3 and r["omitted_edges"] == 0
    r = graph.subgraph(g, "hub", max_nodes=11, max_edges=4)
    assert len(r["edges"]) == 4 and r["omitted_edges"] == 6


def test_edges_to_orphans_are_dropped():
    g = graph.build([ch("a", ["o", "missing", "b"]), ch("b"), ch("o", status="orphaned")])
    r = graph.subgraph(g, "a")
    assert sorted(ids(r)) == ["a", "b"]
    assert r["edges"] == [{"from": "a", "to": "b", "kind": "arrow"}]


def test_shortest_path_directed_and_undirected():
    g = graph.build(
        [ch("a", ["b", "x"]), ch("b", ["c"]), ch("x", ["y"]), ch("y", ["c"]), ch("c"), ch("z")]
    )
    p = graph.path(g, "a", "c")
    assert p["found"] and p["length"] == 2 and ids(p) == ["a", "b", "c"]
    assert graph.path(g, "c", "a", direction="in")["found"]
    assert graph.path(g, "c", "a", direction="out")["found"] is False
    assert graph.path(g, "a", "a")["length"] == 0
    assert graph.path(g, "a", "z")["found"] is False


def test_components_sorted_and_capped():
    g = graph.build(chain("a", "b", "c") + [ch("d", ["e"]), ch("e"), ch("f")])
    r = graph.components(g)
    assert [c["size"] for c in r["components"]] == [3, 2, 1]
    assert r["chunk_count"] == 6 and r["component_count"] == 3 and r["isolated"] == 1
    r = graph.components(g, max_components=1, max_ids=2)
    assert r["omitted_components"] == 2
    assert len(r["components"][0]["chunk_ids"]) == 2 and r["components"][0]["omitted_ids"] == 1


def test_mermaid_is_a_flowchart_and_sanitised():
    nodes = [
        {"id": "aaa", "kind": "handwriting", "text": 'say "hi"] <script>\nx' + "y" * 100},
        {"id": "bbb", "kind": "diagram", "text": None},
        {"id": "ccc", "kind": "diagram", "text": "hidden"},
    ]
    edges = [{"from": "aaa", "to": "bbb", "kind": "arrow"}]
    src = graph.mermaid(nodes[:2], edges + [{"from": "aaa", "to": "ccc", "kind": "arrow"}])
    assert mermaid.is_flowchart(src)
    lines = src.splitlines()
    assert lines[0] == "flowchart TD" and "aaa" not in src
    label = re.match(r'\s+n1\["(.*)"\]$', lines[1]).group(1)
    assert not re.search(r"[\"\[\]<>\n]", label) and 0 < len(label) <= graph.LABEL
    assert 'n2["diagram"]' in lines[2]
    assert [ln for ln in lines if "-->" in ln] == ["  n1 --> n2"]
