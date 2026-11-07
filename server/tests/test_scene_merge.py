"""INK-111 (decision 0080): saves merge element by element under the write lock."""

import itertools
import json

import pytest

from inkbridge import db
from tests.test_regions_api import SCENE


def el(id, version, nonce=0, **extra):
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


def rows(conn):
    return {
        r["id"]: json.loads(r["json"])
        for r in conn.execute("SELECT id, json FROM scene_elements ORDER BY id")
    }


def head(conn):
    return conn.execute("SELECT version FROM scenes WHERE document_id = 'default'").fetchone()[0]


@pytest.fixture
def conn(client):
    c = db.connect()
    yield c
    c.close()


def merge(conn, batch, **kw):
    kw.setdefault("strict", True)
    return db.merge_elements(conn, "default", batch, **kw)


def test_batch_orders_converge(client, tmp_path, monkeypatch):
    batches = [
        [el("x", 3, 10, tag="x3"), el("y", 2, 50, tag="y2a"), el("z", 1, 5, tag="z1")],
        [el("x", 2, 1, tag="x2"), el("y", 2, 20, tag="y2b"), el("z", 2, 9, tag="z2", isDeleted=True)],
        [el("y", 2, 90, tag="y2c"), el("z", 3, 4, tag="z3"), el("x", 4, 7, tag="x4", isDeleted=True)],
    ]
    # x: v4 deleted wins. y: tie at v2, lowest nonce 20 wins (y2b). z: v3 live again (undo).
    results = []
    for n, order in enumerate(itertools.permutations(batches)):
        monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / f"o{n}.db"))
        db.init_db()
        c = db.connect()
        try:
            for batch in order:
                merge(c, batch)
            results.append(rows(c))
        finally:
            c.close()
    assert len(results) == 6
    assert all(r == results[0] for r in results)
    got = results[0]
    assert (got["x"]["tag"], got["x"]["isDeleted"]) == ("x4", True)
    assert got["y"]["tag"] == "y2b"
    assert (got["z"]["tag"], got["z"]["isDeleted"]) == ("z3", False)


def test_tie_goes_to_the_lower_nonce_in_either_order(client, conn):
    a, b = el("x", 5, 10, tag="A"), el("x", 5, 20, tag="B")
    merge(conn, [a])
    merge(conn, [b])
    assert rows(conn)["x"]["tag"] == "A"
    conn.execute("DELETE FROM scene_elements")
    conn.commit()
    merge(conn, [b])
    merge(conn, [a])
    assert rows(conn)["x"]["tag"] == "A"


def test_an_old_full_scene_put_cannot_delete_or_roll_back_newer_ink(client, conn):
    merge(conn, [el("x", 5, tag="new"), el("y", 1), el("z", 3, isDeleted=True)])
    base = head(conn)
    r = client.put(
        SCENE, json={"base_version": 0, "elements": [el("x", 2, tag="old"), el("z", 1, tag="old")]}
    )
    assert r.status_code == 200
    got = rows(conn)
    assert got["x"]["version"] == 5 and got["x"]["tag"] == "new"
    assert "y" in got and not got["y"]["isDeleted"]
    assert got["z"]["isDeleted"] and got["z"]["version"] == 3
    newer = {e["id"]: e for e in r.json()["newer"]}
    assert set(newer) == {"x", "y", "z"}
    assert newer["x"]["version"] == 5 and newer["z"]["isDeleted"] is True
    assert r.json()["seq"] == base == head(conn)  # nothing in the PUT beat a stored row


def test_no_change_does_not_bump_or_run_the_chunker(client, conn, monkeypatch):
    calls = []
    real = db.scenes._sync_chunks
    monkeypatch.setattr(db.scenes, "_sync_chunks", lambda *a, **k: calls.append(1) or real(*a, **k))
    batch = [el("x", 1), el("y", 1)]
    first = merge(conn, batch)
    second = merge(conn, batch)
    assert second.seq == first.seq and head(conn) == first.seq
    assert second.changed == 0
    assert len(calls) == 1


def test_changed_batch_bumps_the_head_once_and_stamps_rows(client, conn):
    merge(conn, [el("a", 1), el("b", 1), el("c", 1), el("keep", 1)])
    base = head(conn)
    r = merge(conn, [el("a", 2), el("b", 2), el("c", 2)])
    assert r.seq == base + 1 == head(conn)
    seqs = dict(conn.execute("SELECT id, seq FROM scene_elements").fetchall())
    assert seqs == {"a": base + 1, "b": base + 1, "c": base + 1, "keep": base}


def test_winner_comes_back_as_newer_and_equal_stamp_does_not(client, conn):
    merge(conn, [el("x", 5, 3, tag="stored")])
    r = merge(conn, [el("x", 4, 1, tag="loser")])
    assert [e["tag"] for e in r.newer] == ["stored"] and r.changed == 0
    again = merge(conn, [el("x", 5, 3, tag="stored")])
    assert again.newer == [] and again.changed == 0
    assert rows(conn)["x"]["tag"] == "stored"


def test_newer_is_a_stub_for_a_shrunk_tombstone(client, conn):
    from datetime import datetime, timedelta

    merge(conn, [el("x", 1)])
    merge(conn, [el("x", 2, 4, isDeleted=True)])
    pos = conn.execute("SELECT pos FROM scene_elements WHERE id = 'x'").fetchone()[0]
    later = (datetime.fromisoformat(db._now()) + timedelta(days=15)).isoformat()
    db.shrink_tombstones(conn, "default", later)
    conn.commit()
    r = merge(conn, [el("x", 1)])
    assert r.newer == [{"id": "x", "version": 2, "versionNonce": 4, "isDeleted": True}]
    merge(conn, [el("x", 3, tag="back")])
    full = rows(conn)["x"]
    assert full["tag"] == "back" and "type" in full
    assert conn.execute("SELECT pos FROM scene_elements WHERE id = 'x'").fetchone()[0] == pos


def test_put_returns_rows_the_other_device_wrote_since_base_version(client, conn):
    merge(conn, [el("a", 1)])  # seq 1
    merge(conn, [el("b", 1)])  # seq 2
    other = merge(conn, [el("c", 1)], base_seq=1)  # sends c only
    assert [e["id"] for e in other.newer] == ["b"]
    assert merge(conn, [el("d", 1)], base_seq=3).newer == []
    r = merge(conn, [el("e", 1)], base_seq=head(conn))
    assert r.newer == []


def test_replay_returns_the_first_seq_and_changes_nothing(client, conn):
    first = merge(conn, [el("x", 1, tag="first")], key="d1:1")
    second = merge(conn, [el("x", 9, tag="second"), el("y", 1)], key="d1:1")
    assert second.replay and second.seq == first.seq and second.newer == [] and second.changed == 0
    assert set(rows(conn)) == {"x"} and rows(conn)["x"]["tag"] == "first"


def test_refused_batch_stores_nothing_and_records_no_key(client, conn):
    draft = el("d", 1, customData={"draft": True, "op_id": "o1"})
    with pytest.raises(db.ElementsRefused) as e:
        merge(conn, [el("ok", 1), draft], key="d1:1")
    assert e.value.ids == ["d"]
    assert rows(conn) == {} and not db._applied
    assert merge(conn, [el("ok", 1)], key="d1:1").seq == 1  # the key is free again


def test_total_rows_over_the_cap_rolls_back(client, conn):
    with pytest.raises(db.SceneTooLarge):
        merge(conn, [el("a", 1), el("b", 1), el("c", 1)], max_elements=2)
    assert rows(conn) == {} and head(conn) == 0


def test_legacy_mode_stores_drafts(client, conn):
    # INK-114 deletes this test with the `strict` flag: drafts keep living in the scene until then.
    merge(conn, [el("d", 1, customData={"draft": True}), el("op1:0", 1)], strict=False)
    assert set(rows(conn)) == {"d", "op1:0"}
