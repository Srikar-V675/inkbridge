"""INK-096: one limit for what is readable; chunks past it say so instead of being sent anywhere."""

from inkbridge import imaging
from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import rect

CHUNKS = "/documents/default/chunks"


def test_limits_are_pinned():
    assert imaging.MAX_READ_UNITS == 4096 and imaging.MAX_CROP_ELEMENTS == 1500


def test_unreadable_reason_boundaries():
    ok = {"width": 4096, "height": 10}
    assert imaging.unreadable_reason(ok, 1500) is None
    assert imaging.unreadable_reason({"width": 10, "height": 4096}, 1) is None
    assert imaging.unreadable_reason({"width": 4097, "height": 10}, 1)
    assert imaging.unreadable_reason({"width": 10, "height": 4097}, 1)
    assert imaging.unreadable_reason(ok, 1501)
    assert "split the chunk" in imaging.unreadable_reason({"width": 5000, "height": 40}, 3)


def test_outline_flags_the_too_large_chunk_only(client):
    Canvas(client, row("n", 3, x=0, y=0) + [rect("big", 0, 2000, w=5000, h=50)])
    chunks = {c["element_ids"][0]: c for c in client.get(CHUNKS).json()["chunks"]}
    assert chunks["n0"]["read_status"] == "ok" and chunks["n0"]["read_note"] is None
    assert chunks["big"]["read_status"] == "too_large"
    assert "split" in chunks["big"]["read_note"]


def test_check_sync_does_not_wait_for_a_too_large_chunk():
    from inkbridge.db.sync import needs_reading

    def region(rid, width):
        return {"id": rid, "content_hash": "new", "source": None, "png_stale": 0,
                "bounds": {"width": width, "height": 10}, "stroke_count": 3}  # fmt: skip

    note = {"hash": "old"}
    resolved = [(note, region("ok", 100), None), (note, region("big", 5000), None)]
    assert needs_reading(resolved) == ["ok"]
