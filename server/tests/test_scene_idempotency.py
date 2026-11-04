"""Idempotent scene saves (INK-083): a repeated X-Inkbridge-Save key replays, never conflicts."""

from inkbridge import api
from tests.test_regions_api import SCENE, A, B


def put(client, key, base, els=(A,), url=SCENE):
    return client.put(
        url,
        json={"base_version": base, "elements": list(els)},
        headers={"x-inkbridge-save": key} if key else {},
    )


def test_repeated_key_replays_without_conflict(client):
    assert put(client, "t1:1", 0).json() == {"version": 1}
    r = put(client, "t1:1", 0)
    assert r.status_code == 200 and r.json() == {"version": 1}
    assert client.get(SCENE).json()["version"] == 1


def test_new_key_with_stale_base_still_conflicts(client):
    put(client, "t1:1", 0)
    assert put(client, "t1:2", 0).status_code == 409
    assert put(client, None, 0).status_code == 409


def test_same_key_on_another_document_does_not_collide(client):
    other = client.post("/documents", json={"title": "other"}).json()["id"]
    url = f"/documents/{other}/scene"
    put(client, "t1:1", 0)
    r = put(client, "t1:1", 0, url=url)
    assert r.status_code == 200 and client.get(url).json()["version"] == 1


def test_conflict_names_the_last_writer(client):
    put(client, "t1:1", 0)
    r = put(client, "t2:1", 0)
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "current_version": 1,
        "last_writer": {"tab": "t1", "same_ip": True},
    }


def test_rolled_back_save_does_not_record_the_key(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_ELEMENTS", 1)
    assert put(client, "t1:1", 0, els=[A, B]).status_code == 422
    monkeypatch.setattr(api, "MAX_ELEMENTS", 10)
    r = put(client, "t1:1", 0, els=[A, B])
    assert r.status_code == 200 and r.json() == {"version": 1}
    assert len(client.get(SCENE).json()["elements"]) == 2
