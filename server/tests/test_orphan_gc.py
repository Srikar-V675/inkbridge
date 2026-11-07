"""INK-087: orphaned auto chunks are collected on scene save (newest N, max age, successor chains kept)."""

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from inkbridge import config, db
from tests.test_check_sync import check, note_of, read
from tests.test_chunk_persistence import Canvas, row
from tests.test_region_staleness import make_region
from tests.test_region_staleness import region as get


def one(sql, *args):
    conn = db.connect()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def orphan_count():
    return one("SELECT count(*) FROM regions WHERE status='orphaned' AND created_by='auto'")


def execute(sql, *args):
    conn = db.connect()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def touch_crops():
    conn = db.connect()
    try:
        for r in conn.execute("SELECT png_path FROM regions WHERE created_by='auto'"):
            p = Path(r["png_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
    finally:
        conn.close()


def days_ago(n):
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def churn_cluster(canvas, prefix, n=10, y=2000):
    """Replace one cluster with all-new ids n times, leaving the other elements alone."""
    keep = [e for e in canvas.elements if not e["id"].startswith(prefix)]
    for i in range(n):
        canvas.elements = keep + row(f"{prefix}{i}_", 4, y=y)
        canvas.put()


def test_churn_keeps_orphans_and_crops_bounded(client):
    canvas = Canvas(client, row("g0_", 4))
    for i in range(1, 101):
        touch_crops()
        canvas.elements = row(f"g{i}_", 4)
        canvas.put()
    assert orphan_count() <= db.ORPHAN_KEEP
    assert one("SELECT count(*) FROM regions") <= db.ORPHAN_KEEP + 1
    files = {str(p) for p in config.crops_dir().glob("*.png")}
    conn = db.connect()
    paths = {r["png_path"] for r in conn.execute("SELECT png_path FROM regions")}
    conn.close()
    assert len(files) <= db.ORPHAN_KEEP + 1
    assert files <= paths  # no file leaked for a deleted row


def test_gc_removes_recognitions_fts_and_links_of_deleted_orphans(client, monkeypatch):
    monkeypatch.setattr(db.chunks, "ORPHAN_KEEP", 1)
    canvas = Canvas(client, row("a0_", 4))
    first = canvas.chunk_of("a0_0")
    read(first, "first words")
    for i in (1, 2):
        canvas.elements = row(f"a{i}_", 4)
        canvas.put()
    assert one("SELECT count(*) FROM regions WHERE id = ?", first["id"]) == 0
    assert one("SELECT count(*) FROM recognitions WHERE region_id = ?", first["id"]) == 0
    assert one("SELECT count(*) FROM region_fts WHERE region_id = ?", first["id"]) == 0
    assert (
        one(
            "SELECT count(*) FROM links WHERE from_region NOT IN (SELECT id FROM regions)"
            " OR to_region NOT IN (SELECT id FROM regions)"
        )
        == 0
    )


def test_orphan_inside_window_is_still_reactivated_by_undo(client):
    canvas = Canvas(client, row("e", 10))
    original = canvas.chunk_of("e0")
    saved = copy.deepcopy(canvas.elements)
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    churn_cluster(canvas, "z", 10)
    canvas.elements = saved + [e for e in canvas.elements if e["id"].startswith("z")]
    canvas.put()
    assert canvas.chunk_of("e0")["id"] == original["id"]


def test_old_orphan_is_collected_but_successor_chain_survives(client):
    canvas = Canvas(client, row("p", 6) + row("q", 6, x=1090, start=6))
    p, q = canvas.chunk_of("p0"), canvas.chunk_of("q6")
    for i in range(6, 12):
        canvas.el(f"q{i}")["x"] -= 1000
    canvas.put()
    execute("UPDATE regions SET updated_at = ? WHERE id = ?", days_ago(30), p["id"])
    canvas.el("q6")["y"] += 1  # a save that changes nothing collects nothing (decision 0080)
    canvas.put()  # a save collects
    assert one("SELECT count(*) FROM regions WHERE id = ?", p["id"]) == 0
    assert one("SELECT count(*) FROM regions WHERE id = ?", q["id"]) == 1

    # chain: kept orphan X points at old orphan Y; Y must survive
    churn_cluster(canvas, "w", 3, y=3000)
    x, y = [c["id"] for c in canvas.chunks("orphaned")][:2]
    execute("UPDATE regions SET updated_at = ? WHERE id = ?", days_ago(30), y)
    execute("UPDATE regions SET successor_of = ?, updated_at = ? WHERE id = ?", y, days_ago(0), x)
    canvas.el("q6")["y"] += 1
    canvas.put()
    assert one("SELECT count(*) FROM regions WHERE id = ?", y) == 1
    assert get(client, x)["id"] == x


def test_active_and_manual_regions_never_collected(client, monkeypatch):
    monkeypatch.setattr(db.chunks, "ORPHAN_KEEP", 0)
    canvas = Canvas(client, row("a", 4) + row("m", 3, y=900))
    manual = make_region(client, ["m0", "m1"])
    for i in range(3):
        canvas.el(f"m{i}")["isDeleted"] = True  # orphans the manual region and its chunk
    canvas.put()
    canvas.put()
    assert get(client, manual["id"])["status"] == "orphaned"
    assert len(canvas.chunks("active")) == 1
    assert orphan_count() == 0  # auto orphans went, manual stayed


def test_check_sync_follows_successor_after_gc(client):
    canvas = Canvas(client, row("e", 10))
    read(canvas.chunk_of("e0"), "ten strokes")
    note = [note_of(canvas.chunk_of("e0"))]
    for i in range(5, 10):
        canvas.el(f"e{i}")["y"] += 400
    canvas.put()
    read(canvas.chunk_of("e0"), "first half")
    churn_cluster(canvas, "z", 10)
    result = check(client, note)
    assert result["removed"] == []
    assert [r["id"] for r in result["replaced"]] == [note[0]["id"]]
