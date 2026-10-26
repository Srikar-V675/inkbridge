"""INK-059: manual chunk merge and split. Overrides are server state; the ink is never touched."""

import copy
import json

import pytest

from inkbridge import db
from tests.test_chunk_persistence import Canvas, row, stroke
from tests.test_chunker import arrow, rect
from tests.test_regions_api import REGIONS, SCENE, post

MERGE = "/documents/default/chunks/merge"
SPLIT = "/documents/default/chunks/split"


def raw_scene(client):
    """The stored scene exactly as the database holds it (version and JSON text)."""
    conn = db.connect()
    try:
        return db.get_scene(conn, "default")
    finally:
        conn.close()


@pytest.fixture
def page(client):
    # Two rows far apart: two chunks, a (5 strokes) and b (3 strokes).
    return Canvas(client, row("a", 5) + row("b", 3, y=500))


def test_merge_makes_one_pinned_chunk_and_orphans_the_originals(client, page):
    a, b = page.chunk_of("a0"), page.chunk_of("b0")
    r = client.post(MERGE, json={"chunk_ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    merged = r.json()["chunk"]
    assert merged["id"] not in (a["id"], b["id"])
    assert set(merged["element_ids"]) == set(a["element_ids"]) | set(b["element_ids"])
    assert merged["pinned"] is True and merged["status"] == "active" and merged["png_stale"] is True
    assert sorted(r.json()["orphaned"]) == sorted([a["id"], b["id"]])
    for old in (a, b):
        got = client.get(f"/regions/{old['id']}").json()
        assert got["status"] == "orphaned" and got["successor_of"] == merged["id"]
        assert got["pinned"] is False
    assert [c["id"] for c in page.chunks("active")] == [merged["id"]]


def test_split_makes_two_pinned_chunks_and_a_later_save_keeps_them(client, page):
    a = page.chunk_of("a0")
    r = client.post(SPLIT, json={"chunk_id": a["id"], "element_ids": ["a0", "a1"]})
    assert r.status_code == 200, r.text
    picked, rest = r.json()["chunks"]
    assert picked["element_ids"] == ["a0", "a1"] and rest["element_ids"] == ["a2", "a3", "a4"]
    assert picked["pinned"] and rest["pinned"]
    old = client.get(f"/regions/{a['id']}").json()
    # The larger part takes over the original, so a note linked to it follows the bigger half.
    assert old["status"] == "orphaned" and old["successor_of"] == rest["id"]

    # Later automatic runs (an unrelated edit, a no-op save, ink touching both halves) keep the split.
    page.elements.append(stroke("far", 2000, 2000))
    page.put()
    page.el("a1")["x"] += 1
    page.el("a1")["version"] += 1
    page.put()
    page.put()
    assert page.chunk_of("a0")["id"] == picked["id"] and page.chunk_of("a0")["element_ids"] == [
        "a0",
        "a1",
    ]
    assert page.chunk_of("a4")["id"] == rest["id"] and page.chunk_of("a4")["element_ids"] == [
        "a2",
        "a3",
        "a4",
    ]
    # New ink right next to a pinned chunk starts its own chunk instead of joining it.
    page.elements.append(stroke("new", 75, 0))
    page.put()
    assert page.chunk_of("new")["element_ids"] == ["new"]
    assert page.chunk_of("a4")["id"] == rest["id"]
    # Erasing all of a pinned chunk orphans it and drops its pin, so it constrains nothing.
    for i in ("a0", "a1"):
        page.el(i)["isDeleted"] = True
        page.el(i)["version"] += 1
    page.put()
    gone = client.get(f"/regions/{picked['id']}").json()
    assert gone["status"] == "orphaned" and gone["pinned"] is False


def test_merge_survives_later_saves_and_deleting_one_stroke(client, page):
    a, b = page.chunk_of("a0"), page.chunk_of("b0")
    merged = client.post(MERGE, json={"chunk_ids": [a["id"], b["id"]]}).json()["chunk"]
    page.elements.append(stroke("far", 2000, 2000))
    page.put()
    page.el("b2")["isDeleted"] = True
    page.el("b2")["version"] += 1
    page.put()
    got = page.chunk_of("a0")
    assert (
        got["id"] == merged["id"] and "b0" in got["element_ids"] and "b2" not in got["element_ids"]
    )
    assert got["pinned"] is True


def test_overrides_never_modify_or_delete_elements(client, page):
    before = raw_scene(client)
    a, b = page.chunk_of("a0"), page.chunk_of("b0")
    merged = client.post(MERGE, json={"chunk_ids": [a["id"], b["id"]]}).json()["chunk"]
    client.post(SPLIT, json={"chunk_id": merged["id"], "element_ids": ["b0", "b1", "b2"]})
    assert raw_scene(client) == before  # same version, byte-identical elements
    # The browser's next save, built on the same version, is still accepted.
    page.put()


def test_resplitting_and_remerging_pinned_chunks(client, page):
    a = page.chunk_of("a0")
    picked, rest = client.post(SPLIT, json={"chunk_id": a["id"], "element_ids": ["a0"]}).json()[
        "chunks"
    ]
    r = client.post(MERGE, json={"chunk_ids": [picked["id"], rest["id"]]})
    assert r.status_code == 200
    merged = r.json()["chunk"]
    assert merged["element_ids"] == [f"a{i}" for i in range(5)] and merged["pinned"]
    assert {c["id"] for c in page.chunks("active")} == {merged["id"], page.chunk_of("b0")["id"]}


def test_arrows_attach_to_a_pinned_chunk_and_link_instead_of_merging(client):
    page = Canvas(
        client,
        [rect("n1", 0, 0, 100, 100), rect("n2", 300, 0, 100, 100), rect("m", 0, 1000, 100, 100)],
    )
    n1, m = page.chunk_of("n1"), page.chunk_of("m")
    merged = client.post(MERGE, json={"chunk_ids": [n1["id"], m["id"]]}).json()["chunk"]
    # A short arrow from the merged chunk to n2 would merge them without the pin.
    page.elements.append(arrow("ar", 100, 50, 200, start="n1", end="n2"))
    page.put()
    got = page.chunk_of("n1")
    assert (
        got["id"] == merged["id"] and "ar" in got["element_ids"] and "n2" not in got["element_ids"]
    )
    conn = db.connect()
    try:
        links = db.list_links(conn, "default")
    finally:
        conn.close()
    assert links == [{"from": merged["id"], "to": page.chunk_of("n2")["id"], "kind": "arrow"}]


def test_bound_text_goes_with_its_container_when_split(client):
    label = {
        "id": "label",
        "type": "text",
        "x": 10,
        "y": 10,
        "width": 20,
        "height": 10,
        "containerId": "box",
        "version": 1,
    }
    page = Canvas(client, [rect("box", 0, 0, version=1), label, rect("near", 110, 0, version=1)])
    c = page.chunk_of("box")
    r = client.post(SPLIT, json={"chunk_id": c["id"], "element_ids": ["box"]})
    assert r.status_code == 200, r.text
    assert r.json()["chunks"][0]["element_ids"] == ["box", "label"]


def test_bad_requests(client, page):
    a, b = page.chunk_of("a0"), page.chunk_of("b0")
    manual = post(client, ["a0"]).json()["id"]

    def merge(ids, doc="default"):
        return client.post(f"/documents/{doc}/chunks/merge", json={"chunk_ids": ids})

    def split(cid, ids):
        return client.post(SPLIT, json={"chunk_id": cid, "element_ids": ids})

    assert merge([a["id"], b["id"]], doc="nope").status_code == 404
    assert merge([a["id"]]).status_code == 422
    assert merge([a["id"], a["id"]]).status_code == 422
    assert merge([a["id"], "unknown"]).status_code == 404
    assert merge([a["id"], manual]).status_code == 404  # a manual region is not a chunk
    assert split("unknown", ["a0"]).status_code == 404
    assert split(a["id"], []).status_code == 422
    assert split(a["id"], ["b0"]).status_code == 422  # not in this chunk
    assert split(a["id"], [f"a{i}" for i in range(5)]).status_code == 422  # nothing left
    detail = split(a["id"], ["zz"]).json()["detail"]
    assert "zz" in json.dumps(detail)
    # An orphaned chunk is stale: the caller should reload the chunk list.
    client.post(MERGE, json={"chunk_ids": [a["id"], b["id"]]})
    r = split(a["id"], ["a0"])
    assert r.status_code == 409 and "orphaned" in r.text
    # A chunk of another canvas is not found on this one.
    conn = db.connect()
    try:
        conn.execute("INSERT INTO documents (id, title, updated_at) VALUES ('other', 'o', 'now')")
        conn.execute(
            "INSERT INTO scenes (document_id, version, elements_json, updated_at) VALUES ('other', 0, '[]', 'now')"
        )
        conn.commit()
    finally:
        conn.close()
    other = client.put(
        "/documents/other/scene", json={"base_version": 0, "elements": [stroke("o1", 0, 0)]}
    )
    assert other.status_code == 200
    (oc,) = client.get("/documents/other/regions", params={"chunks": True}).json()
    assert merge([page.chunk_of("a0")["id"], oc["id"]]).status_code == 404


def test_split_selection_of_only_a_connector_is_rejected(client):
    page = Canvas(client, [rect("n1", 0, 0, 100, 100), arrow("ar", 100, 50, 900, start="n1")])
    c = page.chunk_of("n1")
    assert "ar" in c["element_ids"]
    assert client.post(SPLIT, json={"chunk_id": c["id"], "element_ids": ["ar"]}).status_code == 422


def test_scene_rows_unchanged_and_regions_listing_still_manual_only(client, page):
    elements = copy.deepcopy(page.elements)
    a, b = page.chunk_of("a0"), page.chunk_of("b0")
    client.post(MERGE, json={"chunk_ids": [a["id"], b["id"]]})
    assert client.get(SCENE).json()["elements"] == elements
    assert client.get(REGIONS).json() == []  # overrides are chunks, not manual regions
