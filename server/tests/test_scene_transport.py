"""INK-080: the scene GET is gzipped when accepted and returns the stored JSON verbatim."""

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


def test_scene_body_is_the_stored_json_verbatim(client):
    Canvas(client, row("a", 3))
    body = client.get(SCENE, headers={"Accept-Encoding": "identity"}).content
    stored = json.loads(body)
    assert list(stored) == ["version", "elements"]
    assert stored["elements"][0]["id"].startswith("a")
