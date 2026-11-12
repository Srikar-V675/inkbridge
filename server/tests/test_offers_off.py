"""Offers are off by default (INK-206): nothing scans, reads ink or pushes a chip."""

from inkbridge import config
from inkbridge.api import offers


def test_default_is_off(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_OFFERS", raising=False)
    assert config.offers_enabled() is False
    for on in ("1", "true", "ON", "yes"):
        monkeypatch.setenv("INKBRIDGE_OFFERS", on)
        assert config.offers_enabled() is True
    monkeypatch.setenv("INKBRIDGE_OFFERS", "0")
    assert config.offers_enabled() is False


def test_off_scan_and_flush_do_nothing(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_OFFERS", raising=False)
    monkeypatch.setattr(offers.db, "connect", lambda: (_ for _ in ()).throw(AssertionError("db")))
    offers.scan_now("doc")
    offers.flush("doc")
    offers.schedule_scan("doc")
    assert "doc" not in offers._scans


def test_health_reports_offers(client, monkeypatch):
    assert client.get("/health").json()["offers"] is True
    monkeypatch.delenv("INKBRIDGE_OFFERS", raising=False)
    assert client.get("/health").json()["offers"] is False
