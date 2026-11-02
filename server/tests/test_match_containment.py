"""INK-072 item 4: containment matching, behind INKBRIDGE_CHUNK_CONTAINMENT, off by default."""

import pytest

from inkbridge import config, db
from inkbridge.chunker import ChunkerConfig, match_chunks
from tests.test_chunk_persistence import Canvas, row

OLD = {"c1": ["a", "b"]}
GREW = [["a", "b", "x", "y", "z"]]  # 2 elements gain 3: J = 0.4


def kept(m):  # id kept by the single cluster
    return m.assigned[0]


def test_default_keeps_jaccard_behaviour():
    assert kept(match_chunks(OLD, GREW, tops=[0])) is None


def test_containment_keeps_the_id_when_the_old_ink_survives():
    assert kept(match_chunks(OLD, GREW, tops=[0], containment=0.6)) == "c1"


def test_containment_keeps_the_id_when_a_chunk_shrinks():
    m = match_chunks({"c1": list("abcde")}, [["a", "b"]], tops=[0], containment=0.6)
    assert kept(m) == "c1"


def test_containment_does_not_steal_from_a_better_jaccard_match():
    old = {"big": list("abcdefghij"), "small": ["k", "l"]}
    m = match_chunks(old, [list("abcdefghijkl")], tops=[0], containment=0.6)
    assert kept(m) == "big"  # higher J goes first


def test_unrelated_clusters_stay_new():
    old = {"c1": ["a", "b", "c"]}
    assert kept(match_chunks(old, [["a", "x", "y", "z"]], tops=[0], containment=0.6)) is None


def test_config_validates_containment():
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            ChunkerConfig(match_containment=bad)
    assert ChunkerConfig().match_containment is None


@pytest.mark.parametrize(
    ("value", "want"),
    [(None, None), ("", None), ("0.6", 0.6), ("0", None), ("abc", None), ("2", None), ("1", 1.0)],
)
def test_env_flag(monkeypatch, value, want):
    monkeypatch.delenv("INKBRIDGE_CHUNK_CONTAINMENT", raising=False)
    if value is not None:
        monkeypatch.setenv("INKBRIDGE_CHUNK_CONTAINMENT", value)
    assert config.chunk_containment() == want


def grown(client, cfg):
    canvas = Canvas(client, row("a", 2))
    before = canvas.chunk_of("a0")["id"]
    canvas.elements += row("a", 5, start=2)
    conn = db.connect()
    try:
        canvas.version = db.put_scene(
            conn, "default", canvas.version, __import__("json").dumps(canvas.elements), cfg
        )
    finally:
        conn.close()
    return before, canvas.chunks("active")


def test_the_config_reaches_the_database_matching(client):
    before, (chunk,) = grown(client, ChunkerConfig(match_containment=0.6))
    assert chunk["id"] == before


def test_default_config_gives_the_grown_chunk_a_new_id(client):
    before, (chunk,) = grown(client, ChunkerConfig())
    assert chunk["id"] != before
    orphan = client.get(f"/regions/{before}").json()
    assert orphan["status"] == "orphaned" and orphan["successor_of"] == chunk["id"]


def test_the_env_flag_is_used_when_no_config_is_passed(client, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CHUNK_CONTAINMENT", "0.6")
    before, (chunk,) = grown(client, None)
    assert chunk["id"] == before
