"""INK-072: region_fts must match what _reindex_region would produce (also checked after every test)."""

from inkbridge import db
from tests.fts_check import fts_problems
from tests.test_regions_api import SCENE, A, B, post
from tests.test_search import recognise, search


def test_detector_bites_and_clean_state_passes(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    recognise(ra, "hello world", source="user")
    conn = db.connect()
    try:
        assert fts_problems(conn) == []
        conn.execute("DELETE FROM region_fts")
        assert any("no fts row" in p for p in fts_problems(conn))
        conn.execute("INSERT INTO region_fts (region_id, text, latex) VALUES ('ghost', 'x', '')")
        assert any("missing region" in p for p in fts_problems(conn))
        conn.execute("DELETE FROM region_fts")
        db._reindex_region(conn, ra["id"])
        conn.commit()
        assert fts_problems(conn) == []
    finally:
        conn.close()


def test_scene_edit_after_reading_leaves_index_consistent(client):
    client.put(SCENE, json={"base_version": 0, "elements": [A, B]})
    ra = post(client, ["a"]).json()
    recognise(ra, "hello world")
    client.put(
        SCENE, json={"base_version": 1, "elements": [{**A, "points": [[0, 0], [31, 41]]}, B]}
    )
    assert search(client, "hello") == []
    conn = db.connect()
    try:
        assert fts_problems(conn) == []
    finally:
        conn.close()
