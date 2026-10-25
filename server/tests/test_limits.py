"""Request body caps: oversized bodies get 413 before the app parses them; valid ones are untouched."""

import json

import pytest

from inkbridge.api import limits
from tests.test_regions_api import PNG, REGIONS, SCENE, A, B, post, seed


@pytest.fixture
def small_caps(monkeypatch):
    monkeypatch.setattr(limits, "MAX_BODY_BYTES", 2_000)
    monkeypatch.setattr(limits, "MAX_IMAGE_BODY_BYTES", 1_000)


def big_scene(n=100):
    return {"base_version": 0, "elements": [{**A, "id": f"e{i}"} for i in range(n)]}


def test_oversized_scene_is_413_and_not_stored(client, small_caps):
    r = client.put(SCENE, json=big_scene())
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]
    assert client.get(SCENE).json() == {"version": 0, "elements": []}


def test_oversized_chunked_scene_without_content_length_is_413(client, small_caps):
    body = json.dumps(big_scene()).encode()

    def chunks():
        for i in range(0, len(body), 256):
            yield body[i : i + 256]

    r = client.put(SCENE, content=chunks(), headers={"content-type": "application/json"})
    assert r.request.headers.get("content-length") is None  # really exercised the streaming path
    assert r.status_code == 413
    assert client.get(SCENE).json()["version"] == 0


def test_scene_under_the_cap_is_unchanged(client, small_caps):
    r = client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    assert r.status_code == 200 and r.json() == {"version": 1}
    assert client.get(SCENE).json()["elements"] == [A, B]


def test_chunked_scene_under_the_cap_is_replayed_intact(client, small_caps):
    body = json.dumps({"base_version": 0, "elements": [A]}).encode()
    r = client.put(
        SCENE, content=iter([body[:10], body[10:]]), headers={"content-type": "application/json"}
    )
    assert r.status_code == 200
    assert client.get(SCENE).json()["elements"] == [A]


def test_oversized_region_upload_is_413(client, small_caps):
    seed(client)
    r = post(client, ["a"], png=PNG + b"\0" * 2_000)
    assert r.status_code == 413
    assert client.get(REGIONS).json() == []


def test_oversized_image_replacement_is_413(client, small_caps):
    seed(client)
    rid = post(client, ["a"]).json()["id"]
    r = client.put(
        f"/regions/{rid}/image", files={"image": ("r.png", PNG + b"\0" * 2_000, "image/png")}
    )
    assert r.status_code == 413
    assert client.get(f"/regions/{rid}/image").content == PNG


def test_image_routes_use_the_image_cap_not_the_general_one(client, monkeypatch):
    monkeypatch.setattr(limits, "MAX_BODY_BYTES", 100_000)
    monkeypatch.setattr(limits, "MAX_IMAGE_BODY_BYTES", 1_000)
    seed(client)
    assert post(client, ["a"], png=PNG + b"\0" * 2_000).status_code == 413
    # The scene route still takes the same size under the general cap.
    assert client.put(SCENE, json=big_scene(10) | {"base_version": 1}).status_code == 200


def test_default_caps_fit_the_documented_limits():
    from inkbridge.api.regions import MAX_UPLOAD_BYTES

    assert limits.MAX_IMAGE_BODY_BYTES > MAX_UPLOAD_BYTES  # multipart framing fits on top
    assert limits.MAX_BODY_BYTES >= 128 * 1024 * 1024  # ~3,800 dense 35 KB strokes


def test_bodyless_requests_and_health_are_unaffected(client, small_caps):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get(SCENE).status_code == 200


def test_declared_oversized_length_is_rejected_without_reading_the_body():
    import asyncio

    async def app(scope, receive, send):
        raise AssertionError("the app must not run")

    async def receive():
        raise AssertionError("the body must not be read")

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/documents/default/scene",
        "headers": [(b"content-length", str(limits.MAX_BODY_BYTES + 1).encode())],
    }
    asyncio.run(limits.BodySizeLimit(app)(scope, receive, send))
    assert sent[0]["status"] == 413
