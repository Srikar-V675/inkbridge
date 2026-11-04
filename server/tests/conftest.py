import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inkbridge import db
from inkbridge.api import app
from tests.fts_check import fts_problems
from tests.integrity_check import successor_problems


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:  # context manager runs the lifespan (DB init)
        yield c


@pytest.fixture(autouse=True)
def fts_consistent(monkeypatch, request):
    yield
    if request.node.get_closest_marker("fts_unchecked"):
        return  # test edits tables behind the index's back on purpose (also skips the successor_of check)
    path = os.environ.get("INKBRIDGE_DB")
    if path and Path(path).exists():
        conn = db.connect(Path(path))
        try:
            if "region_fts" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}:
                assert fts_problems(conn) == []
            assert successor_problems(conn) == []
        finally:
            conn.close()
