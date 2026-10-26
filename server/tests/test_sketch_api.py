"""GET /regions/{id}/sketch and /sketch.png (INK-058)."""

import io

from PIL import Image

from inkbridge import db
from tests.test_regions_api import post
from tests.test_sketch import line, loop, v_head

SCENE = "/documents/default/scene"
SKETCH = [
    loop("box1", 0, 0, 100, 60),
    loop("box2", 300, 0, 100, 60),
    line("shaft", (105, 30), (295, 30)),
    v_head("head", (295, 30)),
]


def seed(client, elements=SKETCH):
    assert client.put(SCENE, json={"base_version": 0, "elements": elements}).status_code == 200


def test_sketch_of_a_region_lists_nodes_arrows_and_markers(client):
    seed(client)
    rid = post(client, ["box1", "box2", "shaft", "head"], kind="diagram").json()["id"]
    out = client.get(f"/regions/{rid}/sketch").json()
    assert [n["id"] for n in out["nodes"]] == ["N1", "N2"]
    (arrow,) = out["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"]) == ("N1", "N2", "end")
    assert {m["id"] for m in out["markers"]} == {"N1", "N2", "A1"}
    r = client.get(f"/regions/{rid}/sketch.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).format == "PNG"


def test_sketch_follows_arrow_links_one_hop(client):
    # Long arrows split a sketch into one chunk per node joined by links: reading the first
    # chunk must still find the arrow's target.
    seed(client)
    a = post(client, ["box1", "shaft", "head"]).json()["id"]
    b = post(client, ["box2"]).json()["id"]
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO links (document_id, from_region, to_region, kind)"
            " VALUES ('default', ?, ?, 'arrow')",
            (a, b),
        )
        conn.commit()
    finally:
        conn.close()
    out = client.get(f"/regions/{a}/sketch").json()
    assert len(out["nodes"]) == 2 and len(out["arrows"]) == 1 and out["unattached"] == []


def test_drafts_are_not_part_of_the_sketch(client):
    draft = {**loop("draft-box", 600, 0, 100, 60), "customData": {"draft": True, "op_id": "x"}}
    seed(client, [*SKETCH, draft])
    rid = post(client, ["box1", "box2", "shaft", "head", "draft-box"]).json()["id"]
    out = client.get(f"/regions/{rid}/sketch").json()
    assert len(out["nodes"]) == 2


def test_unknown_region_is_404(client):
    assert client.get("/regions/nope/sketch").status_code == 404
    assert client.get("/regions/nope/sketch.png").status_code == 404
