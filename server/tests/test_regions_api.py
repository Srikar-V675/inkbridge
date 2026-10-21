import base64

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
SCENE = "/documents/default/scene"
REGIONS = "/documents/default/regions"

A = {
    "id": "a",
    "type": "freedraw",
    "x": 10,
    "y": 20,
    "width": 30,
    "height": 40,
    "points": [[0, 0], [30, 40]],
    "pressures": [0.3, 0.6],
    "version": 1,
}
B = {
    "id": "b",
    "type": "freedraw",
    "x": -5,
    "y": 0,
    "width": 10,
    "height": 100,
    "points": [[0, 0], [10, 100]],
    "pressures": [0.4, 0.8],
    "version": 1,
}


def seed(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})


def post(client, ids, png=PNG, **extra):
    import json

    return client.post(
        REGIONS,
        data={"element_ids": json.dumps(ids), **extra},
        files={"image": ("crop.png", png, "image/png")},
    )


def test_create_region_computes_bbox_and_hash_server_side(client):
    seed(client)
    r = post(client, ["a", "b"])
    assert r.status_code == 201
    body = r.json()
    assert body["bounds"] == {"x": -5, "y": 0, "width": 45, "height": 100}
    assert body["stroke_count"] == 2 and body["status"] == "active"
    assert len(body["stroke_hash"]) == 64


def test_unknown_element_id_is_rejected(client):
    seed(client)
    assert post(client, ["a", "nope"]).status_code == 422
    assert client.get(REGIONS).json() == []


def test_empty_selection_and_non_png_are_rejected(client):
    seed(client)
    assert post(client, []).status_code == 422
    assert post(client, ["a"], png=b"not a png").status_code == 422


def test_unknown_document_is_404(client):
    r = client.post(
        "/documents/nope/regions",
        data={"element_ids": '["a"]'},
        files={"image": ("c.png", PNG, "image/png")},
    )
    assert r.status_code == 404


def test_get_list_and_image(client):
    seed(client)
    rid = post(client, ["a"], kind="handwriting").json()["id"]
    one = client.get(f"/regions/{rid}").json()
    assert one["element_ids"] == ["a"] and one["kind"] == "handwriting"
    assert one["text"] is None
    listed = client.get(REGIONS).json()
    assert [x["id"] for x in listed] == [rid]
    assert client.get(REGIONS, params={"kind": "equation"}).json() == []
    img = client.get(f"/regions/{rid}/image")
    assert img.status_code == 200 and img.content == PNG
    assert img.headers["content-type"] == "image/png"


def test_unknown_region_is_404(client):
    assert client.get("/regions/nope").status_code == 404
    assert client.get("/regions/nope/image").status_code == 404


def test_region_ink_returns_points_and_pressures(client):
    seed(client)
    rid = post(client, ["a", "b"]).json()["id"]
    ink = client.get(f"/regions/{rid}/ink").json()
    assert ink["point_count"] == 4
    first = ink["strokes"][0]
    assert (first["id"], first["points"], first["pressures"]) == ("a", A["points"], A["pressures"])
    assert client.get("/regions/nope/ink").status_code == 404


def big_png(w, h):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def test_image_endpoint_caps_width_but_stored_crop_is_untouched(client):
    import io

    from PIL import Image

    seed(client)
    original = big_png(3000, 600)
    rid = post(client, ["a"], png=original).json()["id"]
    capped = client.get(f"/regions/{rid}/image").content
    assert Image.open(io.BytesIO(capped)).size == (1024, 205)
    full = client.get(f"/regions/{rid}/image", params={"max_width": 4000}).content
    assert full == original


def test_corrupt_png_with_valid_magic_is_rejected(client):
    seed(client)
    truncated = PNG[:20]
    assert post(client, ["a"], png=truncated).status_code == 422


def test_ink_endpoint_decimates_to_max_points(client):
    n = 6000
    wide = {**A, "id": "w", "points": [[i, i] for i in range(n)], "pressures": [0.5] * n}
    client.put(SCENE, json={"base_version": 0, "elements": [wide]})
    rid = post(client, ["w"]).json()["id"]
    ink = client.get(f"/regions/{rid}/ink").json()
    assert ink["point_count"] <= 5000 and ink["decimated"] is True
    assert ink["original_point_count"] == n
    full = client.get(f"/regions/{rid}/ink", params={"max_points": 10000}).json()
    assert full["point_count"] == n and full["decimated"] is False


def test_ink_includes_stroke_origin_so_layout_can_be_rebuilt(client):
    seed(client)
    rid = post(client, ["a", "b"]).json()["id"]
    strokes = {st["id"]: st for st in client.get(f"/regions/{rid}/ink").json()["strokes"]}
    assert (strokes["a"]["x"], strokes["a"]["y"]) == (10, 20)
    assert (strokes["b"]["x"], strokes["b"]["y"]) == (-5, 0)
    assert "angle" in strokes["a"]


def test_put_image_replaces_crop_and_clears_stale_flag(client):
    seed(client)
    rid = post(client, ["a"]).json()["id"]
    client.put(
        SCENE, json={"base_version": 1, "elements": [{**A, "points": [[0, 0], [31, 41]]}, B]}
    )
    assert client.get(f"/regions/{rid}").json()["png_stale"] is True
    new = big_png(40, 20)
    r = client.put(f"/regions/{rid}/image", files={"image": ("c.png", new, "image/png")})
    assert r.status_code == 200 and r.json()["png_stale"] is False
    assert client.get(f"/regions/{rid}/image").content == new
    bad = client.put(f"/regions/{rid}/image", files={"image": ("c.png", b"nope", "image/png")})
    assert bad.status_code == 422
    missing = client.put("/regions/nope/image", files={"image": ("c.png", new, "image/png")})
    assert missing.status_code == 404


def test_scene_element_without_id_is_422_not_500(client):
    r = client.put(SCENE, json={"base_version": 0, "elements": [{"type": "freedraw"}]})
    assert r.status_code == 422


def test_list_limit_is_bounded_and_unknown_document_is_404(client):
    assert client.get(REGIONS, params={"limit": -1}).status_code == 422
    assert client.get("/documents/typo/regions").status_code == 404


def test_duplicate_element_ids_are_collapsed(client):
    seed(client)
    assert post(client, ["a", "a", "b"]).json()["stroke_count"] == 2


def test_failed_db_insert_leaves_no_orphan_file(client, tmp_path):
    seed(client)
    assert post(client, ["a", "nope"]).status_code == 422
    crops = tmp_path / "crops"
    assert not crops.exists() or list(crops.iterdir()) == []
