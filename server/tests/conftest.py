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
    db._applied.clear()
    with TestClient(app) as c:  # context manager runs the lifespan (DB init)
        yield c


@pytest.fixture(autouse=True)
def offers_on(monkeypatch):
    """Offers are off by default since INK-206; the offers tests exercise the code, so switch it on.

    `test_offers_off.py` deletes this variable to check the default.
    """
    monkeypatch.setenv("INKBRIDGE_OFFERS", "1")


@pytest.fixture(autouse=True)
def reset_activity():
    # The working dot (INK-198) is one module-level tracker; a task left running by one test must
    # not be replayed to the next test's WebSocket.
    from inkbridge.agent.activity import activity

    activity.configure(None)
    activity._live.clear()
    activity._last.clear()
    yield
    activity.configure(None)
    activity._live.clear()
    activity._last.clear()


@pytest.fixture(autouse=True)
def legacy_chunker_v1(monkeypatch):
    """Most chunk tests were written against v1; the default is v2 since INK-195 (decision 0110).

    Tests of the default `delenv` this first; tests of v2 use the `v2` fixture or a canvas setting.
    """
    monkeypatch.setenv("INKBRIDGE_CHUNKER", "v1")


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
