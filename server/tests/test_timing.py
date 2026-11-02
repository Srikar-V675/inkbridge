"""INK-067: timing logs carry names, counts and milliseconds, never content."""

import logging

import pytest

from inkbridge import timing
from inkbridge.timing import timed
from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import SCENE


def test_timed_logs_name_and_ms_not_payload(caplog):
    secret = "PRIVATE-INK-TEXT"  # noqa: F841 - must never reach a log
    with caplog.at_level(logging.INFO, logger="inkbridge.timing"):
        with timed("demo", elements=3):
            pass
        with timed("x", elements=1):
            pass
    msgs = [r.getMessage() for r in caplog.records if r.name == "inkbridge.timing"]
    assert len(msgs) == 2
    assert "demo" in msgs[0] and "elements=3" in msgs[0] and "ms=" in msgs[0]
    assert "PRIVATE-INK-TEXT" not in caplog.text
    with pytest.raises(TypeError):
        with timed("bad", text="PRIVATE-INK-TEXT"):  # type: ignore[arg-type]
            pass


def request_records(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "inkbridge.request"]


def test_request_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="inkbridge.request"):
        client.get("/health")
    (msg,) = request_records(caplog)
    assert "GET" in msg and "/health" in msg and "200" in msg and "ms=" in msg


def test_request_logs_route_template_not_body(client, caplog):
    el = row("a", 2)
    el[0]["text"] = "PRIVATE-INK-TEXT"
    with caplog.at_level(logging.INFO):
        Canvas(client, el)
    assert any("/documents/{document_id}/scene" in m for m in request_records(caplog))
    assert "PRIVATE-INK-TEXT" not in caplog.text
    assert SCENE  # the raw path (with the id) is not what gets logged
    assert not any("/documents/default/" in m for m in request_records(caplog))


def test_slow_request_flagged(client, caplog, monkeypatch):
    monkeypatch.setattr(timing, "SLOW_S", -1.0)
    with caplog.at_level(logging.INFO, logger="inkbridge.request"):
        client.get("/health")
    assert [r.levelno for r in caplog.records if r.name == "inkbridge.request"] == [logging.WARNING]
