from fastapi.testclient import TestClient

from inkbridge.api import app


def test_health(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_CROP_SOURCE", raising=False)
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "crop_source": "browser"}


def test_health_in_server_crop_mode(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CROP_SOURCE", "server")
    assert TestClient(app).get("/health").json() == {"status": "ok", "crop_source": "server"}
