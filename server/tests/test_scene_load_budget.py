"""INK-080: the real-scale fixture scene must stay big (so this guards something) and compress well."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

import make_real_scale

from tests.test_regions_api import SCENE


def test_fixture_scene_gzips_to_a_fraction(client):
    els = make_real_scale.build()
    base = client.get(SCENE).json()["version"]
    assert client.put(SCENE, json={"base_version": base, "elements": els}).status_code == 200
    plain = client.get(SCENE, headers={"Accept-Encoding": "identity"}).content
    zipped = client.get(SCENE, headers={"Accept-Encoding": "gzip"})
    assert zipped.headers["content-encoding"] == "gzip"
    assert len(plain) >= 500_000  # still real scale
    assert int(zipped.headers["content-length"]) <= 0.35 * len(plain)
