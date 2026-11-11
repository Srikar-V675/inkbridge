"""INK-130: the attention gate and quiet_s config."""

import pytest

from inkbridge import config
from inkbridge.agent.attention import Attention


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setenv("INKBRIDGE_QUIET_S", "8")


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_closed_until_a_message():
    assert Attention(Clock()).can_push("d") is False


def test_pen_down_blocks():
    c = Clock()
    a = Attention(c)
    a.update("d", pen=True)
    c.t = 100
    assert a.can_push("d") is False


def test_quiet_window():
    c = Clock()
    a = Attention(c)
    a.update("d", pen=False)
    c.t = 7.9
    assert a.can_push("d") is False
    c.t = 8.0
    assert a.can_push("d") is True
    c.t = 10
    a.update("d", pen=True)
    a.update("d", pen=False)
    c.t = 17
    assert a.can_push("d") is False
    c.t = 18
    assert a.can_push("d") is True


def test_remaining():
    c = Clock()
    a = Attention(c)
    assert a.remaining("d") is None
    a.update("d", pen=False)
    assert a.remaining("d") == 8
    c.t = 5
    assert a.remaining("d") == 3
    a.update("d", pen=True)
    assert a.remaining("d") is None


def test_forget():
    c = Clock()
    a = Attention(c)
    a.update("d", pen=False)
    c.t = 50
    assert a.can_push("d")
    a.forget("d")
    assert a.can_push("d") is False


def test_quiet_s_config(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_QUIET_S")
    assert config.quiet_s() == 3.0
    monkeypatch.setenv("INKBRIDGE_QUIET_S", "2.5")
    assert config.quiet_s() == 2.5
    for bad in ("junk", "-1"):
        monkeypatch.setenv("INKBRIDGE_QUIET_S", bad)
        assert config.quiet_s() == 3.0


def test_view_tick_while_up_does_not_reset():
    c = Clock()
    a = Attention(c)
    a.update("d", pen=False)
    c.t = 8
    a.update("d", pen=False, view={"x": 1})
    assert a.can_push("d") is True
