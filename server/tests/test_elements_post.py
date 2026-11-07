"""INK-111 (decision 0080): POST /documents/{id}/elements, the batch route with N1."""


from inkbridge import api, db
from tests.test_regions_api import SCENE

URL = "/documents/default/elements"
PARTS = ("recv", "queue", "lock", "work", "commit", "total")


def el(id, version=1, nonce=0, **extra):
    return {
        "id": id,
        "type": "freedraw",
        "x": 0,
        "y": 0,
        "width": 10,
        "height": 20,
        "points": [[0, 0], [10, 20]],
        "pressures": [0.5, 0.5],
        "isDeleted": False,
        "version": version,
        "versionNonce": nonce,
        **extra,
    }


def post(client, elements, device="d1", batch=1, url=URL):
    return client.post(url, json={"device": device, "batch": batch, "elements": elements})


def published(monkeypatch):
    sent = []
    monkeypatch.setattr(api.ws.hub, "publish", lambda d, m: sent.append(m))
    return sent


def test_post_returns_seq_newer_and_timing(client):
    r = post(client, [el("x")])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"seq", "newer", "timing"}
    assert body["seq"] == 1 and body["newer"] == []
    assert all(k in body["timing"] for k in PARTS)
    assert [e["id"] for e in client.get(SCENE).json()["elements"]] == ["x"]


def test_post_refuses_a_draft_flagged_element(client):
    # N1: fails if the `strict` check is removed from merge_elements
    draft = el("x", customData={"draft": True, "op_id": "o1", "author": "agent"})
    r = post(client, [el("ok"), draft], batch=7)
    assert r.status_code == 422
    assert r.json()["detail"]["refused"] == ["x"]
    assert client.get(SCENE).json()["elements"] == []
    assert not db._applied
    assert post(client, [el("ok"), el("x")], batch=7).status_code == 200  # the key was not recorded


def test_post_refuses_a_new_op_prefixed_id(client):
    assert post(client, [el("abc123def456:0")]).status_code == 422
    seed = client.put(SCENE, json={"base_version": 0, "elements": [el("abc123def456:0")]})
    assert seed.status_code == 200  # the legacy route still stores it (INK-114)
    r = post(client, [el("abc123def456:0", 2)], batch=2)
    assert r.status_code == 200
    assert client.get(SCENE).json()["elements"][0]["version"] == 2


def test_post_batch_is_idempotent(client, monkeypatch):
    sent = published(monkeypatch)
    first = post(client, [el("x")])
    again = post(client, [el("x", 9), el("y")])  # same (device, batch): a replay
    assert again.status_code == 200 and again.json()["seq"] == first.json()["seq"]
    assert again.json()["newer"] == []
    assert len(sent) == 1
    assert [e["id"] for e in client.get(SCENE).json()["elements"]] == ["x"]


def test_post_same_batch_number_from_another_device_is_not_a_replay(client):
    post(client, [el("x")], device="d1", batch=1)
    r = post(client, [el("y")], device="d2", batch=1)
    assert r.json()["seq"] == 2
    assert {e["id"] for e in client.get(SCENE).json()["elements"]} == {"x", "y"}


def test_post_loser_comes_back_in_newer(client, monkeypatch):
    post(client, [el("x", 5, tag="stored")], batch=1)
    sent = published(monkeypatch)
    r = post(client, [el("x", 3, tag="loser")], batch=2)
    assert r.status_code == 200
    assert [e["tag"] for e in r.json()["newer"]] == ["stored"]
    assert r.json()["seq"] == 1 and sent == []
    assert client.get(SCENE).json()["elements"][0]["tag"] == "stored"


def test_post_validation_matches_the_scene_put(client, monkeypatch):
    bad = [
        [{"type": "freedraw"}],
        [{"id": 5}],
        [{"id": "a", "type": "freedraw", "points": [[1]]}],
        [{"id": "a", "pressures": ["x"]}],
    ]
    for elements in bad:
        r = client.post(URL, json={"device": "d1", "batch": 1, "elements": elements})
        assert r.status_code == 422, elements
    for literal in ("NaN", "Infinity", "-Infinity"):
        raw = f'{{"device":"d1","batch":1,"elements":[{{"id":"a","x":{literal}}}]}}'.encode()
        r = client.post(URL, content=raw, headers={"content-type": "application/json"})
        assert r.status_code == 422, literal
    monkeypatch.setattr(api, "MAX_ELEMENTS", 2)
    assert post(client, [el("a"), el("b"), el("c")]).status_code == 422  # batch over the cap
    assert post(client, [el("a"), el("b")], batch=2).status_code == 200
    assert post(client, [el("c")], batch=3).status_code == 422  # rows over the cap
    for device in ("has space", "x" * 65, ""):
        assert post(client, [el("z")], device=device).status_code == 422
    assert post(client, [el("z")], batch=-1).status_code == 422
    assert post(client, [el("z")], url="/documents/nope/elements").status_code == 404


def test_post_publishes_chunks_updated_once_when_something_changed(client, monkeypatch):
    sent = published(monkeypatch)
    r = post(client, [el("x"), el("y")])
    assert len(sent) == 1
    assert sent[0]["type"] == "chunks.updated" and sent[0]["version"] == r.json()["seq"]
    post(client, [el("x"), el("y")], batch=2)  # nothing changed
    assert len(sent) == 1
