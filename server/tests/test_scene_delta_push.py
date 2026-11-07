"""INK-112 (decision 0087): scene.delta goes to every device except the writer."""

from tests.test_elements_post import el, post
from tests.test_regions_api import SCENE
from tests.test_ws import recv

WS = "/ws?document=default&device="


def test_delta_goes_to_other_device_not_origin(client):
    # fails if the origin skip in Hub.send is removed (a1 would get its own delta)
    with client.websocket_connect(WS + "a1") as a, client.websocket_connect(WS + "b1") as b:
        s1 = el("s1")
        r = post(client, [s1], device="a1", batch=0)
        assert recv(b) == {"type": "scene.delta", "seq": r.json()["seq"], "origin": "a1", "elements": [s1]}
        assert recv(a)["type"] == "chunks.updated"
        post(client, [el("s2")], device="b1", batch=0)
        m = recv(a)
        assert m["type"] == "scene.delta" and m["origin"] == "b1"


def test_loser_replay_and_draft_not_published(client):
    with client.websocket_connect(WS + "c1") as c:
        post(client, [el("s1", version=5)], device="a1", batch=0)
        assert recv(c)["type"] == "scene.delta"
        assert recv(c)["type"] == "chunks.updated"
        post(client, [el("s1", version=5)], device="a1", batch=0)  # replay
        post(client, [el("s1", version=2)], device="a1", batch=1)  # loses
        draft = el("d1", customData={"draft": True, "op_id": "o1", "author": "agent"})
        client.put(
            SCENE,
            json={"base_version": 0, "elements": [draft]},
            headers={"X-Inkbridge-Save": "tab9:1"},
        )
        assert recv(c)["type"] == "chunks.updated"  # draft write: crops only, no delta


def test_put_origin_is_save_key_tab(client):
    with client.websocket_connect(WS + "tab9") as t, client.websocket_connect(WS + "z") as z:
        client.put(
            SCENE,
            json={"base_version": 0, "elements": [el("s1")]},
            headers={"X-Inkbridge-Save": "tab9:1"},
        )
        m = recv(z)
        assert m["type"] == "scene.delta" and m["origin"] == "tab9"
        assert recv(t)["type"] == "chunks.updated"
