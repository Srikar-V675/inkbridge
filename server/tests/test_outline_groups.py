"""INK-123: the chunk outline carries link label and confidence, group_id and the top-level groups."""

from tests.test_chunk_persistence import Canvas
from tests.test_chunker import arrow, rect
from tests.test_regions_api import _orphan

OUTLINE = "/documents/default/chunks"


def two_hubs(client):
    """Hub A with spokes s1 (right) and s2 (below), hub B with spoke s3, and one lone box."""
    els = [
        rect("hA", 0, 0, 100, 100), rect("s1", 3000, 0, 100, 100), rect("s2", 0, 3000, 100, 100),
        rect("hB", 9000, 0, 100, 100), rect("s3", 12000, 0, 100, 100), rect("x", 30000, 30000, 100, 100),
        arrow("a1", 100, 50, 2800, start="hA", end="s1"),
        arrow("a2", 50, 100, 0, 2800, start="hA", end="s2"),
        arrow("a3", 9100, 50, 2800, start="hB", end="s3"),
    ]  # fmt: skip
    canvas = Canvas(client, els)
    ids = {n: canvas.chunk_of(n)["id"] for n in ("hA", "s1", "s2", "hB", "s3", "x")}
    return canvas, ids


def outline(client, **params):
    return client.get(OUTLINE, params=params).json()


def test_two_hub_fixture_yields_two_groups(client):
    _, ids = two_hubs(client)
    body = outline(client)
    assert len(body["groups"]) == 2
    got = {frozenset(g["chunk_ids"]) for g in body["groups"]}
    assert got == {
        frozenset({ids["hA"], ids["s1"], ids["s2"]}),
        frozenset({ids["hB"], ids["s3"]}),
    }
    group_of = {c["id"]: c["group_id"] for c in body["chunks"]}
    for g in body["groups"]:
        assert all(group_of[cid] == g["id"] for cid in g["chunk_ids"])
    assert group_of[ids["x"]] is None
    assert body["isolated"] == 1


def test_link_has_label_and_confidence(client):
    two_hubs(client)
    links = [link for c in outline(client)["chunks"] for link in c["links"]]
    assert links and all(set(link) == {"to", "kind", "label", "confidence"} for link in links)


def test_orphaned_chunk_has_no_group(client):
    _, ids = two_hubs(client)
    _orphan(ids["s1"])
    body = outline(client, status="all")
    orphan = next(c for c in body["chunks"] if c["id"] == ids["s1"])
    assert orphan["status"] == "orphaned" and orphan["group_id"] is None
