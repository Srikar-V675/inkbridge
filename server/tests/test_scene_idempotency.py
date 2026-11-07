"""Idempotent scene saves (INK-083): a repeated X-Inkbridge-Save key replays, never conflicts."""

from inkbridge import api, db
from tests.test_regions_api import SCENE, A, B


def put(client, key, base, els=(A,), url=SCENE):
    return client.put(
        url,
        json={"base_version": base, "elements": list(els)},
        headers={"x-inkbridge-save": key} if key else {},
    )


def test_repeated_key_replays_without_conflict(client):
    assert put(client, "t1:1", 0).json()["version"] == 1
    r = put(client, "t1:1", 0)
    assert r.status_code == 200 and r.json()["version"] == 1
    assert client.get(SCENE).json()["version"] == 1


def test_stale_base_version_never_conflicts(client):
    put(client, "t1:1", 0)
    r = put(client, "t1:2", 0, els=[B])
    assert r.status_code == 200 and r.json()["version"] == 2
    assert [e["id"] for e in r.json()["newer"]] == ["a"]  # the other device's row since base 0
    assert put(client, None, 0, els=[B]).status_code == 200


def test_same_key_on_another_document_does_not_collide(client):
    other = client.post("/documents", json={"title": "other"}).json()["id"]
    url = f"/documents/{other}/scene"
    put(client, "t1:1", 0)
    r = put(client, "t1:1", 0, url=url)
    assert r.status_code == 200 and client.get(url).json()["version"] == 1


def test_rolled_back_save_does_not_record_the_key(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_ELEMENTS", 1)
    assert put(client, "t1:1", 0, els=[A, B]).status_code == 422
    monkeypatch.setattr(api, "MAX_ELEMENTS", 10)
    r = put(client, "t1:1", 0, els=[A, B])
    assert r.status_code == 200 and r.json()["version"] == 1
    assert len(client.get(SCENE).json()["elements"]) == 2


def test_invalid_key_is_ignored(client):
    put(client, "bad key\nforged", 0)
    assert put(client, "bad key\nforged", 1).status_code == 200  # not remembered, applied again
    assert not db._applied
    assert put(client, "t2:1", 2).status_code == 200


def test_replay_does_not_publish(client, monkeypatch):
    sent = []
    monkeypatch.setattr(api.ws.hub, "publish", lambda d, m: sent.append(m))
    put(client, "t1:1", 0)
    put(client, "t2:1", 1, els=[B])
    n = len(sent)
    assert n == 4  # a scene.delta and a chunks.updated per save
    put(client, "t1:1", 0)  # replay of the first save
    assert len(sent) == n


def test_oldest_key_is_evicted_at_the_cap(client, monkeypatch):
    monkeypatch.setattr(db.scenes, "APPLIED_CAP", 2)
    for i in range(3):
        put(client, f"t1:{i + 1}", i)
    assert [k[1] for k in db._applied] == ["t1:2", "t1:3"]


def test_key_is_recorded_before_the_lock_is_released(client, tmp_path):
    seen = []

    class Conn:
        def __init__(self, c):
            self.c = c

        def commit(self):
            seen.append(("default", "t1:1") in db._applied)
            self.c.commit()

        def __getattr__(self, n):
            return getattr(self.c, n)

    conn = db.connect(tmp_path / "api.db")
    db.put_scene(Conn(conn), "default", 0, "[]", save_key="t1:1")
    assert seen == [True]
