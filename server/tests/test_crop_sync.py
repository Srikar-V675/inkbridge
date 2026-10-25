"""INK-057: the browser lists stale chunk crops and uploads them against the scene version it rendered."""

import sqlite3
from pathlib import Path

from inkbridge import config, db
from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import PNG, REGIONS


def other_png():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (3, 2), "white").save(buf, format="PNG")
    return buf.getvalue()


def stale(client):
    return client.get(REGIONS, params={"chunks": True, "png_stale": True, "limit": 500}).json()


def upload(client, rid, png, version=None):
    data = {} if version is None else {"scene_version": str(version)}
    return client.put(
        f"/regions/{rid}/image", data=data, files={"image": ("c.png", png, "image/png")}
    )


def test_png_stale_filter_lists_only_chunks_that_need_a_crop(client):
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    a, b = canvas.chunk_of("a0"), canvas.chunk_of("b0")
    assert {c["id"] for c in stale(client)} == {a["id"], b["id"]}
    assert upload(client, a["id"], PNG, canvas.version).status_code == 200
    assert [c["id"] for c in stale(client)] == [b["id"]]
    fresh = client.get(REGIONS, params={"chunks": True, "png_stale": False}).json()
    assert [c["id"] for c in fresh] == [a["id"]]


def test_upload_at_the_current_scene_version_clears_png_stale(client):
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    png = other_png()
    r = upload(client, rid, png, canvas.version)
    assert r.status_code == 200 and r.json()["png_stale"] is False
    assert client.get(f"/regions/{rid}/image").content == png


def test_upload_rendered_from_an_older_scene_is_rejected_and_nothing_is_written(client):
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    rendered_at = canvas.version
    canvas.elements[0]["x"] += 5  # the ink moved after the browser rendered its crop
    canvas.put()
    r = upload(client, rid, other_png(), rendered_at)
    assert r.status_code == 409
    assert r.json()["detail"]["current_version"] == canvas.version
    assert canvas.chunk_of("a0")["png_stale"] is True
    assert not Path(config.crops_dir() / f"{rid}.png").exists()  # no file was written


def test_bad_scene_version_is_422(client):
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    assert upload(client, rid, PNG, "x").status_code == 422


def test_upload_without_a_version_keeps_the_old_behaviour(client):
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    assert upload(client, rid, PNG).status_code == 200
    assert canvas.chunk_of("a0")["png_stale"] is False


def test_clear_is_compare_and_set_against_a_save_landing_mid_upload(client):
    """A save between the file write and the clear must leave the crop flagged stale."""
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    rendered_at = canvas.version
    canvas.elements[0]["x"] += 5
    canvas.put()  # lands after the API checked the version and wrote the file
    conn = db.connect()
    try:
        assert db.mark_png_fresh(conn, rid, scene_version=rendered_at) is None
        assert db.get_region(conn, rid)["png_stale"] is True
        assert db.mark_png_fresh(conn, rid, scene_version=canvas.version)["png_stale"] is False
    finally:
        conn.close()


def test_two_uploads_never_share_a_temp_file(client, monkeypatch):
    """Each upload writes its own temp file, so concurrent uploads cannot interleave bytes."""
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    written: list[str] = []
    real = Path.write_bytes

    def spy(self, data):
        written.append(self.name)
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", spy)
    upload(client, rid, PNG, canvas.version)
    upload(client, rid, PNG, canvas.version)
    assert len(written) == 2 and written[0] != written[1]
    assert not list(config.crops_dir().glob("*.tmp"))


def test_check_rename_and_clear_hold_the_scene_write_lock(client, monkeypatch):
    """No save can land between the version check and the clear: it would wait for the lock."""
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunk_of("a0")["id"]
    blocked = []
    real = Path.replace

    def replace_then_try_a_save(self, target):
        other = sqlite3.connect(config.db_path(), timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        except sqlite3.OperationalError as e:
            blocked.append(str(e))
        finally:
            other.close()
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace_then_try_a_save)
    assert upload(client, rid, PNG, canvas.version).status_code == 200
    assert blocked == ["database is locked"]


def test_status_filter_keeps_orphaned_chunks_out_of_the_crop_list(client):
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    gone = canvas.chunk_of("b0")["id"]
    for e in canvas.elements:
        if e["id"].startswith("b"):
            e["isDeleted"] = True
            e["version"] += 1
    canvas.put()
    params = {"chunks": True, "png_stale": True, "status": "active"}
    listed = {c["id"] for c in client.get(REGIONS, params=params).json()}
    assert gone not in listed and canvas.chunk_of("a0")["id"] in listed
    assert gone in {c["id"] for c in stale(client)}  # without the filter it is listed
    assert client.get(REGIONS, params={"status": "nope"}).status_code == 422
