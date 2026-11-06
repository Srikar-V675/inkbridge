"""INK-120: INKBRIDGE_CROP_SOURCE=server renders chunk crops on the server (decision 0065)."""

import io
import os
from pathlib import Path

from PIL import Image

from inkbridge import config, db
from inkbridge.canvas import raster
from inkbridge.db.sync import needs_reading
from tests.test_chunk_persistence import Canvas, row
from tests.test_chunker import rect
from tests.test_recognition_worker import FakeModel, worker
from tests.test_regions_api import PNG


def server_mode(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", "server")


def conn_for_test():
    return db.connect(Path(os.environ["INKBRIDGE_DB"]))


def is_png(data: bytes) -> bool:
    return Image.open(io.BytesIO(data)).format == "PNG"


def test_crop_source_defaults_to_browser_and_ignores_bad_values(monkeypatch, capsys):
    monkeypatch.delenv("INKBRIDGE_CROP_SOURCE", raising=False)
    assert config.crop_source() == "browser"
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", "server")
    assert config.crop_source() == "server"
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", " SERVER ")
    assert config.crop_source() == "server"
    capsys.readouterr()
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", "nope")
    assert config.crop_source() == "browser"
    assert "INKBRIDGE_CROP_SOURCE" in capsys.readouterr().err


def test_render_server_crop_installs_a_fresh_crop(client):
    canvas = Canvas(client, row("a", 4))
    rid = canvas.chunks("active")[0]["id"]
    assert canvas.chunks("active")[0]["png_stale"] is True
    conn = conn_for_test()
    try:
        assert db.render_server_crop(conn, rid) is True
    finally:
        conn.close()
    assert canvas.chunks("active")[0]["png_stale"] is False
    path = Path(os.environ["INKBRIDGE_DB"]).parent / "crops" / f"{rid}.png"
    assert path.exists() and is_png(path.read_bytes())


def test_render_server_crop_loses_the_race_when_the_scene_moved(client, monkeypatch):
    canvas = Canvas(client, row("a", 4))
    rid = canvas.chunks("active")[0]["id"]
    crop = Path(os.environ["INKBRIDGE_DB"]).parent / "crops" / f"{rid}.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"older bytes")
    real = raster.render_crop

    def racing(elements, **kw):
        out = real(elements, **kw)
        canvas.elements[0]["x"] += 5  # a save lands while the server is rendering
        canvas.put()
        return out

    monkeypatch.setattr("inkbridge.db.crops.raster.render_crop", racing)
    conn = conn_for_test()
    try:
        assert db.render_server_crop(conn, rid) is False
    finally:
        conn.close()
    assert canvas.chunks("active")[0]["png_stale"] is True
    assert crop.read_bytes() == b"older bytes"


def test_worker_reads_a_stale_chunk_in_server_mode_with_no_upload(client, monkeypatch):
    canvas = Canvas(client, row("a", 3))
    browser = FakeModel()
    assert worker(browser).run_once() == 0 and browser.calls == []  # old behaviour: stale = skipped
    server_mode(monkeypatch)
    model = FakeModel()
    worker(model).run_once()
    assert len(model.calls) == 1 and is_png(model.calls[0])
    assert canvas.chunks("active")[0]["source"] is not None
    assert canvas.chunks("active")[0]["png_stale"] is False


def test_worker_never_renders_a_too_large_chunk(client, monkeypatch):
    server_mode(monkeypatch)
    canvas = Canvas(client, row("n", 3) + [rect("big", 0, 2000, w=5000, h=50)])
    model = FakeModel()
    worker(model).run_once()
    assert len(model.calls) == 1
    big = canvas.chunk_of("big")
    assert big["png_stale"] is True
    assert not (Path(os.environ["INKBRIDGE_DB"]).parent / "crops" / f"{big['id']}.png").exists()


def test_check_sync_waits_for_stale_chunks_only_in_server_mode(monkeypatch):
    region = {
        "id": "r",
        "content_hash": "new",
        "source": None,
        "png_stale": 1,
        "bounds": {"width": 100, "height": 10},
        "stroke_count": 3,
    }
    resolved = [({"hash": "old"}, region, None)]
    monkeypatch.delenv("INKBRIDGE_CROP_SOURCE", raising=False)
    assert needs_reading(resolved) == []
    server_mode(monkeypatch)
    assert needs_reading(resolved) == ["r"]


def crop_file(rid: str) -> Path:
    return Path(os.environ["INKBRIDGE_DB"]).parent / "crops" / f"{rid}.png"


def test_health_reports_the_crop_source(client, monkeypatch):
    assert client.get("/health").json() == {"status": "ok", "crop_source": "browser"}
    server_mode(monkeypatch)
    assert client.get("/health").json() == {"status": "ok", "crop_source": "server"}


def test_image_png_and_overview_render_on_demand_in_server_mode(client, monkeypatch):
    canvas = Canvas(client, row("a", 4) + row("b", 3, y=500))
    first, second = (c["id"] for c in canvas.chunks("active"))
    assert client.get(f"/regions/{first}/png").status_code == 404  # browser mode: unchanged
    server_mode(monkeypatch)
    image = client.get(f"/regions/{first}/image")
    assert image.status_code == 200 and is_png(image.content)
    png = client.get(f"/regions/{first}/png")
    assert png.status_code == 200 and is_png(png.content)
    assert client.get("/documents/default/overview").status_code == 200
    assert (
        client.get("/documents/default/chunks", params={"png_stale": "true"}).json()["chunks"] == []
    )
    assert crop_file(second).exists()


def test_upload_is_refused_in_server_mode(client, monkeypatch):
    canvas = Canvas(client, row("a", 3))
    rid = canvas.chunks("active")[0]["id"]
    files = {"image": ("c.png", PNG, "image/png")}
    server_mode(monkeypatch)
    r = client.put(
        f"/regions/{rid}/image", data={"scene_version": str(canvas.version)}, files=files
    )
    assert r.status_code == 403 and "server" in r.json()["detail"]
    assert not crop_file(rid).exists()
    monkeypatch.delenv("INKBRIDGE_CROP_SOURCE")
    r = client.put(
        f"/regions/{rid}/image", data={"scene_version": str(canvas.version)}, files=files
    )
    assert r.status_code == 200


def test_overview_renders_at_most_24_stale_chunks_per_call(client, monkeypatch):
    server_mode(monkeypatch)
    monkeypatch.setattr("inkbridge.api.chunks.MAX_RENDER_PER_OVERVIEW", 2)
    canvas = Canvas(client, [s for k in range(4) for s in row(f"c{k}", 3, y=k * 500)])
    assert client.get("/documents/default/overview").status_code == 200
    assert len([c for c in canvas.chunks("active") if not c["png_stale"]]) == 2
    assert client.get("/documents/default/overview").status_code == 200
    assert len([c for c in canvas.chunks("active") if not c["png_stale"]]) == 4  # finishes later


def test_orphaned_region_with_history_returns_existing_crop_and_does_not_render(
    client, monkeypatch
):
    server_mode(monkeypatch)
    canvas = Canvas(client, row("a", 3) + row("b", 3, y=500))
    old = canvas.chunk_of("a0")["id"]
    assert client.get(f"/regions/{old}/png").status_code == 200
    before = crop_file(old).read_bytes()
    canvas.elements = [e for e in canvas.elements if e["id"].startswith("b")]
    canvas.put()  # chunk a is orphaned; its crop file stays
    assert client.get(f"/regions/{old}/png").status_code == 410
    assert client.get(f"/regions/{old}/png", params={"history": "true"}).content == before
    crop_file(old).unlink()
    assert client.get(f"/regions/{old}/png", params={"history": "true"}).status_code == 404
    assert not crop_file(old).exists()  # an orphan is never rendered
