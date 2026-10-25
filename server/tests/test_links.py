"""INK-032: arrows between chunks become links rows, rebuilt on every scene save."""

from inkbridge import db
from tests.test_chunk_persistence import Canvas
from tests.test_chunker import arrow, rect
from tests.test_regions_api import PNG


def links(_canvas):
    conn = db.connect()
    try:
        return db.list_links(conn, "default")
    finally:
        conn.close()


def nodes():
    # Median size 100: an arrow of at most 600 px merges, free ends reach 300 px.
    return [rect("a", 0, 0, 100, 100), rect("b", 2000, 0, 100, 100), rect("c", 0, 2000, 100, 100)]


def check_links_name_active_chunks(canvas):
    active = {c["id"] for c in canvas.chunks("active")}
    for link in links(canvas):
        assert {link["from"], link["to"]} <= active


def test_bound_arrow_links_exactly_the_two_owning_chunks(client):
    canvas = Canvas(client, [*nodes(), arrow("arr", 100, 50, 1900, start="a", end="b")])
    a, b = canvas.chunk_of("a"), canvas.chunk_of("b")
    assert "arr" in a["element_ids"]  # the arrow belongs to the chunk of its start
    assert links(canvas) == [{"from": a["id"], "to": b["id"], "kind": "arrow"}]
    check_links_name_active_chunks(canvas)


def test_free_arrow_links_the_nearest_chunks_and_a_dangling_one_nothing(client):
    canvas = Canvas(client, [*nodes(), arrow("arr", 150, 50, 1800)])
    assert links(canvas) == [
        {"from": canvas.chunk_of("a")["id"], "to": canvas.chunk_of("b")["id"], "kind": "arrow"}
    ]
    canvas.el("arr")["points"][1] = [1000, 0]  # the end now lands in empty space
    canvas.put()
    assert links(canvas) == []
    assert "arr" in canvas.chunk_of("a")["element_ids"]


def test_short_arrow_merges_two_nodes_and_a_long_arrow_stays_a_link(client):
    near = [rect("a", 0, 0, 100, 100), rect("b", 500, 0, 100, 100)]
    canvas = Canvas(client, [*near, arrow("arr", 100, 50, 400, start="a", end="b")])
    (merged,) = canvas.chunks("active")
    assert merged["element_ids"] == ["a", "arr", "b"] and links(canvas) == []
    canvas.el("b")["x"] = 1500  # now 1,400 px long: a link, and the merged chunk splits
    canvas.el("arr")["points"][1] = [1400, 0]
    canvas.put()
    a, b = canvas.chunk_of("a"), canvas.chunk_of("b")
    assert a["id"] != b["id"]
    assert links(canvas) == [{"from": a["id"], "to": b["id"], "kind": "arrow"}]
    check_links_name_active_chunks(canvas)


def test_links_disappear_with_the_arrow_and_never_name_a_missing_chunk(client):
    canvas = Canvas(client, [*nodes(), arrow("arr", 100, 50, 1900, start="a", end="b")])
    assert len(links(canvas)) == 1
    canvas.el("arr")["isDeleted"] = True
    canvas.put()
    assert links(canvas) == []
    canvas.el("arr")["isDeleted"] = False
    canvas.put()
    assert len(links(canvas)) == 1
    canvas.el("b")["isDeleted"] = True  # the target chunk is orphaned: the end is dangling
    canvas.put()
    assert links(canvas) == []
    check_links_name_active_chunks(canvas)


def test_links_are_scoped_to_their_document(client):
    canvas = Canvas(client, [*nodes(), arrow("arr", 100, 50, 1900, start="a", end="b")])
    conn = db.connect()
    try:
        assert db.list_links(conn, "other") == []
    finally:
        conn.close()
    assert len(links(canvas)) == 1


def test_arrow_label_is_part_of_the_arrow_chunk(client):
    label = {
        "id": "lbl",
        "type": "text",
        "x": 1000,
        "y": 40,
        "width": 40,
        "height": 20,
        "text": "calls",
        "containerId": "arr",
    }
    canvas = Canvas(client, [*nodes(), arrow("arr", 100, 50, 1900, start="a", end="b"), label])
    assert canvas.chunk_of("a")["element_ids"] == ["a", "arr", "lbl"]


def test_drawing_an_arrow_out_of_a_chunk_keeps_its_id_and_flags_the_crop(client):
    big = [rect(f"a{i}", 120 * i, 0, 100, 100) for i in range(5)]  # one chunk of 5
    canvas = Canvas(client, [*big, rect("b", 3000, 0, 100, 100)])
    before = canvas.chunk_of("a0")
    r = client.put(f"/regions/{before['id']}/image", files={"image": ("c.png", PNG, "image/png")})
    assert r.json()["png_stale"] is False
    canvas.elements.append(arrow("arr", 580, 50, 2400, start="a4", end="b"))
    canvas.put()
    after = canvas.chunk_of("a0")
    assert after["id"] == before["id"] and "arr" in after["element_ids"]
    assert after["png_stale"] is True and after["content_hash"] != before["content_hash"]
    assert links(canvas) == [
        {"from": after["id"], "to": canvas.chunk_of("b")["id"], "kind": "arrow"}
    ]
