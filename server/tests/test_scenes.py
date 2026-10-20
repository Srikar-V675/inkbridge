SCENE = "/documents/default/scene"

FREEDRAW = {
    "id": "a1",
    "type": "freedraw",
    "x": 10.5,
    "y": -3.25,
    "points": [[0, 0], [1.5, 2.25], [3.125, 4.0625]],
    "pressures": [0.1, 0.5, 0.987654321],
    "simulatePressure": False,
    "customData": {"author": "agent", "draft": True, "op_id": "op-1", "note": "héllo ✍"},
    "version": 7,
    "versionNonce": 123456789,
}


def test_new_document_has_empty_scene_at_version_zero(client):
    r = client.get(SCENE)
    assert r.status_code == 200
    assert r.json() == {"version": 0, "elements": []}


def test_put_then_get_round_trips_and_bumps_version(client):
    r = client.put(SCENE, json={"base_version": 0, "elements": [FREEDRAW]})
    assert r.status_code == 200 and r.json() == {"version": 1}
    assert client.get(SCENE).json() == {"version": 1, "elements": [FREEDRAW]}


def test_pressures_and_custom_data_survive_exactly(client):
    client.put(SCENE, json={"base_version": 0, "elements": [FREEDRAW]})
    el = client.get(SCENE).json()["elements"][0]
    assert el["pressures"] == FREEDRAW["pressures"]
    assert el["simulatePressure"] is False
    assert el["customData"] == FREEDRAW["customData"]


def test_stale_base_version_returns_409_and_does_not_overwrite(client):
    client.put(SCENE, json={"base_version": 0, "elements": [FREEDRAW]})
    r = client.put(SCENE, json={"base_version": 0, "elements": []})
    assert r.status_code == 409
    assert r.json()["detail"] == {"current_version": 1}
    assert client.get(SCENE).json()["elements"] == [FREEDRAW]


def test_version_increments_on_each_successful_put(client):
    for v in range(3):
        r = client.put(SCENE, json={"base_version": v, "elements": []})
        assert r.json() == {"version": v + 1}


def test_unknown_document_is_404(client):
    assert client.get("/documents/nope/scene").status_code == 404
    r = client.put("/documents/nope/scene", json={"base_version": 0, "elements": []})
    assert r.status_code == 404


def test_invalid_body_is_422(client):
    assert client.put(SCENE, json={"elements": []}).status_code == 422
    assert client.put(SCENE, json={"base_version": -1, "elements": []}).status_code == 422
