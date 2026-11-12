from fastapi.testclient import TestClient

from inkbridge.api import app


def test_health(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_CROP_SOURCE", raising=False)
    monkeypatch.delenv("INKBRIDGE_CHUNKER", raising=False)
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {
        "status": "ok",
        "crop_source": "browser",
        "chunker": "v2",
        "offers": True,
    }


def test_health_in_server_crop_mode(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", "server")
    monkeypatch.delenv("INKBRIDGE_CHUNKER", raising=False)
    assert TestClient(app).get("/health").json() == {
        "status": "ok",
        "crop_source": "server",
        "chunker": "v2",
        "offers": True,
    }


def test_health_reports_the_chunker(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v2")
    assert TestClient(app).get("/health").json()["chunker"] == "v2"
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v1")
    assert TestClient(app).get("/health").json()["chunker"] == "v1"
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "bogus")
    assert TestClient(app).get("/health").json()["chunker"] == "v2"
