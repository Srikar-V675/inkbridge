import pytest
from fastapi.testclient import TestClient

from inkbridge.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:  # context manager runs the lifespan (DB init)
        yield c
