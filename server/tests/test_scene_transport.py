"""INK-080: the scene GET is gzipped when accepted. The verbatim-row test lives in test_scene_elements."""

import json

from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import SCENE


def test_large_scene_is_gzipped_when_accepted(client):
    Canvas(client, row("a", 400))
    r = client.get(SCENE, headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert r.json()["version"] >= 1 and len(r.json()["elements"]) == 400


def test_no_gzip_unless_accepted(client):
    Canvas(client, row("a", 400))
    r = client.get(SCENE, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers


def test_images_are_not_gzipped(client):
    import io
    import os

    from PIL import Image

    img = Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    Canvas(client, row("a", 2))
    rid = client.post(
        "/documents/default/regions",
        data={"element_ids": json.dumps(["a0"])},
        files={"image": ("c.png", buf.getvalue(), "image/png")},
    ).json()["id"]
    r = client.get(f"/regions/{rid}/image", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-type"] == "image/png" and len(r.content) > 1024
    assert "content-encoding" not in r.headers
