import asyncio
import json

import pytest

from inkbridge import db
from inkbridge.mcp import server
from inkbridge.mcp.client import ApiClient
from tests.test_regions_api import SCENE, A, B, post


@pytest.fixture
def two_regions(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    rb = post(client, ["b"]).json()
    return ra, rb


def recognise(region, text, source="gemini", latex=None, stroke_hash=None):
    conn = db.connect()
    try:
        db.save_recognition(
            conn, region["id"], stroke_hash or region["stroke_hash"], source, text, latex=latex
        )
    finally:
        conn.close()


def search(client, q, **params):
    r = client.get("/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_search_hits_the_right_region_with_snippet_and_score(client, two_regions):
    ra, rb = two_regions
    recognise(ra, "buy milk and eggs tomorrow")
    recognise(rb, "gradient descent update rule")
    (hit,) = search(client, "milk")
    assert hit["region_id"] == ra["id"]
    assert "[milk]" in hit["snippet"]
    assert isinstance(hit["score"], float) and hit["score"] > 0
    assert [h["region_id"] for h in search(client, "descent")] == [rb["id"]]


def test_prefix_and_multiword_queries(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "buy milk and eggs tomorrow")
    assert len(search(client, "mil")) == 1
    assert len(search(client, "milk eggs")) == 1
    assert search(client, "milk bananas") == []


def test_stale_text_is_replaced_after_ink_change_and_re_recognition(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "hello world")
    assert len(search(client, "hello")) == 1
    # edit the stroke: the old reading no longer describes the ink
    edited = {**A, "points": [[0, 0], [31, 41]]}
    client.put(SCENE, json={"base_version": 1, "elements": [edited, B]})
    assert search(client, "hello") == []
    new_hash = client.get(f"/regions/{ra['id']}").json()["stroke_hash"]
    recognise(ra, "goodbye moon", stroke_hash=new_hash)
    assert [h["region_id"] for h in search(client, "goodbye")] == [ra["id"]]
    assert search(client, "hello") == []


def test_user_text_outranks_agent_and_gemini_in_the_index(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "cat", source="gemini")
    recognise(ra, "kitten", source="agent")
    assert len(search(client, "kitten")) == 1 and search(client, "cat") == []
    recognise(ra, "dog", source="user")
    assert len(search(client, "dog")) == 1 and search(client, "kitten") == []


def test_latex_is_searchable(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "quadratic formula", latex=r"x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}")
    assert len(search(client, "frac")) == 1


def test_hostile_query_syntax_does_not_error(client, two_regions):
    for q in ['a"b', "(", "NEAR(", "a OR", "*", "col:val", "'; DROP TABLE regions;--"]:
        assert isinstance(search(client, q), list)


def test_orphaned_regions_are_not_searchable(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "ghost note")
    client.put(SCENE, json={"base_version": 1, "elements": [{**A, "isDeleted": True}, B]})
    assert search(client, "ghost") == []


def test_limit_and_validation(client, two_regions):
    ra, rb = two_regions
    recognise(ra, "common word")
    recognise(rb, "common word again")
    assert len(search(client, "common", limit=1)) == 1
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_mcp_search_tool(client, two_regions):
    ra, _ = two_regions
    recognise(ra, "buy milk")
    server.set_client(ApiClient(client))
    try:
        result = asyncio.run(server.mcp.call_tool("search", {"query": "milk"}))
    finally:
        server.set_client(None)
    (hit,) = json.loads(result.content[0].text)["results"]
    assert hit["region_id"] == ra["id"] and "[milk]" in hit["snippet"]
