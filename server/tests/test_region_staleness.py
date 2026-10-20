import copy
import json

from tests.test_regions_api import PNG, REGIONS, SCENE, A, B

OTHER = {
    "id": "z",
    "type": "freedraw",
    "x": 500,
    "y": 500,
    "width": 5,
    "height": 5,
    "points": [[0, 0], [5, 5]],
    "pressures": [0.5, 0.5],
    "version": 1,
}


class Scene:
    def __init__(self, client, elements):
        self.client, self.elements = client, elements
        self.version = client.get(SCENE).json()["version"]
        self.put()

    def put(self):
        r = self.client.put(SCENE, json={"base_version": self.version, "elements": self.elements})
        assert r.status_code == 200
        self.version = r.json()["version"]


def make_region(client, ids):
    r = client.post(
        REGIONS, data={"element_ids": json.dumps(ids)}, files={"image": ("c.png", PNG, "image/png")}
    )
    return r.json()


def region(client, rid):
    return client.get(f"/regions/{rid}").json()


def setup(client):
    scene = Scene(client, [copy.deepcopy(x) for x in (A, B, OTHER)])
    return scene, make_region(client, ["a", "b"])


def test_editing_a_stroke_changes_hash_and_flags_png_stale(client):
    scene, reg = setup(client)
    assert reg["png_stale"] is False
    scene.elements[0]["points"][1] = [31, 40]
    scene.put()
    after = region(client, reg["id"])
    assert after["stroke_hash"] != reg["stroke_hash"]
    assert after["png_stale"] is True
    assert after["updated_at"] != reg["updated_at"]


def test_unrelated_edit_leaves_region_untouched(client):
    scene, reg = setup(client)
    scene.elements[2]["x"] = 900
    scene.put()
    assert region(client, reg["id"]) == reg


def test_volatile_field_change_leaves_hash_unchanged(client):
    scene, reg = setup(client)
    scene.elements[0]["version"] = 77
    scene.elements[0]["customData"] = {"author": "agent"}
    scene.put()
    assert region(client, reg["id"]) == reg


def test_deleting_every_stroke_orphans_and_undeleting_restores(client):
    scene, reg = setup(client)
    scene.elements[0]["isDeleted"] = True
    scene.put()
    assert region(client, reg["id"])["status"] == "active"  # one stroke still alive
    scene.elements[1]["isDeleted"] = True
    scene.put()
    assert region(client, reg["id"])["status"] == "orphaned"
    scene.elements[0]["isDeleted"] = False
    scene.elements[1]["isDeleted"] = False
    scene.put()
    restored = region(client, reg["id"])
    assert restored["status"] == "active"
    assert restored["stroke_hash"] == reg["stroke_hash"]


def test_removed_elements_count_as_deleted(client):
    scene, reg = setup(client)
    scene.elements = [scene.elements[2]]
    scene.put()
    assert region(client, reg["id"])["status"] == "orphaned"
