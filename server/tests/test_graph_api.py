"""INK-060: GET /documents/{id}/graph/* over a real canvas."""

import pytest

from inkbridge import mermaid
from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import arrow, rect

G = "/documents/default/graph"


def chain(client, n=4):
    """n far-apart boxes joined by long arrows e0 -> e1 -> ..., plus the Canvas helper."""
    els = []
    for i in range(n):
        els.append(rect(f"r{i}", 3000 * i, 0, 100, 100))
    for i in range(n - 1):
        els.append(arrow(f"a{i}", 3000 * i + 100, 50, 2800, start=f"r{i}", end=f"r{i + 1}"))
    canvas = Canvas(client, els)
    return canvas, [canvas.chunk_of(f"r{i}")["id"] for i in range(n)]


def sub(client, chunk, **params):
    return client.get(f"{G}/subgraph", params={"chunk_id": chunk, **params})


def node_ids(body):
    return {n["id"]: n["distance"] for n in body["nodes"]}


def test_subgraph_returns_reachable_chunks_to_depth(client):
    _, (a, b, c, d) = chain(client)
    body = sub(client, b).json()
    assert node_ids(body) == {b: 0, a: 1, c: 1}
    assert body["anchor_used"] is None and body["note"] is None
    assert body["nodes"][0]["deep_link"].endswith(f"chunk={body['nodes'][0]['id']}")
    assert set(node_ids(sub(client, b, depth=2).json())) == {a, b, c, d}
    assert set(node_ids(sub(client, b, direction="out").json())) == {b, c}


def test_unknown_chunk_404(client):
    chain(client)
    r = sub(client, "nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "chunk_not_found"
    assert client.get("/documents/missing/graph/components").status_code == 404


def test_chunk_from_other_canvas_404(client):
    _, (a, *_) = chain(client)
    other = client.post("/documents", json={"title": "other"}).json()["id"]
    r = client.get(f"/documents/{other}/graph/subgraph", params={"chunk_id": a})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "chunk_not_found"


def split_canvas(client):
    """One chunk of ten strokes, then split in two: the old id is orphaned with a successor."""
    canvas = Canvas(client, row("e", 10))
    old = canvas.chunk_of("e0")["id"]
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    return canvas, old


def test_orphan_with_successor_is_followed(client):
    canvas, old = split_canvas(client)
    live = canvas.chunk_of("e0")["id"]
    r = sub(client, old)
    assert r.status_code == 200
    body = r.json()
    assert body["anchor_used"] == live and old in body["note"] and live in body["note"]
    assert body["center"] == live
    p = client.get(f"{G}/path", params={"from_chunk": old, "to_chunk": live}).json()
    assert p["anchor_used"] == {"from": live, "to": live} and p["length"] == 0


def test_orphan_dead_end_410(client):
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    gone = canvas.chunk_of("a0")["id"]
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    r = sub(client, gone)
    assert r.status_code == 410
    assert r.json()["detail"]["code"] == "chunk_gone" and "read_canvas" in r.json()["detail"]["msg"]


def test_orphaned_chunks_are_not_nodes(client):
    canvas, old = split_canvas(client)
    live = canvas.chunk_of("e0")["id"]
    assert old not in node_ids(sub(client, live, depth=5).json())
    comps = client.get(f"{G}/components").json()
    assert old not in [i for c in comps["components"] for i in c["chunk_ids"]]
    assert comps["chunk_count"] == 2


def test_draft_elements_are_not_nodes(client):
    draft = rect("d", 0, 2000, 100, 100, customData={"draft": True, "author": "agent"})
    Canvas(client, [rect("r", 0, 0, 100, 100), draft])
    assert client.get(f"{G}/components").json()["chunk_count"] == 1


def test_caps_report_omitted(client):
    els = [rect("c", 3000, 3000, 100, 100)]
    for i in range(5):
        x = 6000 * (i % 3) - 3000, 6000 * (i // 3)
        els.append(rect(f"s{i}", x[0], x[1], 100, 100))
    # five spokes: arrows from the centre to each leaf, long enough to stay links
    for i in range(5):
        dx = els[i + 1]["x"] - 3000
        dy = els[i + 1]["y"] - 3000
        els.append(arrow(f"w{i}", 3050, 3050, dx, dy, start="c", end=f"s{i}"))
    canvas = Canvas(client, els)
    centre = canvas.chunk_of("c")["id"]
    body = sub(client, centre, max_nodes=3).json()
    assert len(body["nodes"]) == 3 and body["omitted_nodes"] == 3
    shown = {n["id"] for n in body["nodes"]}
    assert all(e["from"] in shown and e["to"] in shown for e in body["edges"])
    assert len(body["edges"]) + body["omitted_edges"] == 2
    full = sub(client, centre, max_edges=2).json()
    assert len(full["edges"]) == 2 and full["omitted_edges"] == 3


def test_path_found_and_not_found(client):
    _, (a, b, c, d) = chain(client)
    p = client.get(f"{G}/path", params={"from_chunk": a, "to_chunk": d}).json()
    assert p["found"] and p["length"] == 3 and [n["id"] for n in p["nodes"]] == [a, b, c, d]
    p = client.get(f"{G}/path", params={"from_chunk": d, "to_chunk": a, "direction": "out"}).json()
    assert p["found"] is False and p["nodes"] == []


def test_components_lists_groups_and_isolated(client):
    canvas, _ = chain(client)
    canvas.elements.append(rect("lone", 0, 6000, 100, 100))
    canvas.put()
    body = client.get(f"{G}/components").json()
    assert body["chunk_count"] == 5 and body["component_count"] == 2 and body["isolated"] == 1
    assert [c["size"] for c in body["components"]] == [4, 1]


def test_mermaid_param_returns_flowchart(client):
    _, (a, *_) = chain(client)
    assert "mermaid" not in sub(client, a).json()
    src = sub(client, a, mermaid=True).json()["mermaid"]
    assert mermaid.is_flowchart(src) and "n1 --> n2" in src and a not in src


def test_graph_routes_do_not_write(client):
    from inkbridge import db

    _, (a, b, *_) = chain(client)

    def snapshot():
        conn = db.connect()
        try:
            counts = [
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("regions", "links", "scenes", "recognitions")
            ]
            v = conn.execute("SELECT version FROM scenes").fetchone()[0]
        finally:
            conn.close()
        return counts, v

    before = snapshot()
    sub(client, a)
    client.get(f"{G}/path", params={"from_chunk": a, "to_chunk": b})
    client.get(f"{G}/components")
    assert snapshot() == before


@pytest.mark.parametrize("depth", [0, 6])
def test_depth_validation(client, depth):
    _, (a, *_) = chain(client)
    assert sub(client, a, depth=depth).status_code == 422


def test_path_route_404_and_410(client):
    _, (a, *_) = chain(client)
    r = client.get(f"{G}/path", params={"from_chunk": a, "to_chunk": "nope"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "chunk_not_found"
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    gone = canvas.chunk_of("a0")["id"]
    for i in range(3):
        canvas.el(f"a{i}")["isDeleted"] = True
    canvas.put()
    other = canvas.chunk_of("b0")["id"]
    r = client.get(f"{G}/path", params={"from_chunk": other, "to_chunk": gone})
    assert r.status_code == 410 and r.json()["detail"]["code"] == "chunk_gone"
