from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkbridge.api.web import mount_web


def _site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "favicon.svg").write_text("<svg/>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "dev.log").write_text("secret")  # web/dev.log analogue, outside dist
    (tmp_path / "secret.txt").write_text("secret")
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    mount_web(app, dist)
    return TestClient(app)


def test_asset_is_immutable(tmp_path):
    r = _site(tmp_path).get("/assets/app-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]


def test_index_is_no_cache(tmp_path):
    r = _site(tmp_path).get("/")
    assert r.status_code == 200 and "id=root" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_nothing_outside_dist(tmp_path):
    c = _site(tmp_path)
    for path in (
        "/dev.log",
        "/../dev.log",
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/..%2f..%2fsecret.txt",
        "/__log",
        "/secret.txt",
        "/assets/missing.js",
    ):
        assert c.get(path).status_code == 404, path


def test_api_routes_still_win(tmp_path):
    assert _site(tmp_path).get("/health").json() == {"status": "ok"}


def test_missing_dist_is_api_only(tmp_path):
    app = FastAPI()
    assert mount_web(app, tmp_path / "nope") is False
    assert TestClient(app).get("/").status_code == 404


def test_dist_without_assets_is_api_only(tmp_path):
    (tmp_path / "index.html").write_text("x")
    assert mount_web(FastAPI(), tmp_path) is False


def test_real_app_has_no_log_endpoint():
    from inkbridge.api import app

    assert TestClient(app).post("/__log", content="x").status_code in (404, 405)
