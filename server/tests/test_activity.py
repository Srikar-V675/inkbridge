"""INK-198 (decision 0113): the agent working dot. Tracker unit tests first, then wiring and socket."""

import pytest

from inkbridge.agent.activity import STALE_S, Activity, activity


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def tracker():
    sent: list[tuple[str, dict]] = []
    clock = Clock()
    a = Activity(clock=clock)
    a.configure(lambda doc, msg: sent.append((doc, msg)))
    return a, sent, clock


def test_begin_end_publishes_changes():
    a, sent, _ = tracker()
    a.begin("d", "reading", "read:r1")
    assert sent[-1] == ("d", {"type": "agent.activity", "working": True, "what": "reading", "count": 1})
    a.begin("d", "reading", "read:r2")
    assert sent[-1][1]["count"] == 2
    a.end("d", "read:r1")
    assert sent[-1][1]["count"] == 1
    a.end("d", "read:r2")
    assert sent[-1][1] == {"type": "agent.activity", "working": False, "what": "reading", "count": 0}
    assert len(sent) == 4


def test_priority():
    a, _, _ = tracker()
    a.begin("d", "reading", "read:r1")
    a.begin("d", "answer", "task:t1")
    assert a.snapshot("d")["what"] == "answer"
    a.end("d", "task:t1")
    a.begin("d", "task", "task:t2")
    assert a.snapshot("d")["what"] == "task"


def test_no_publish_when_unchanged():
    a, sent, _ = tracker()
    a.begin("d", "reading", "read:r1")
    a.begin("d", "reading", "read:r1")  # same key, same triple
    a.end("d", "read:unknown")  # nothing in flight under that key
    assert len(sent) == 1


def test_stale_key_dropped():
    a, _, clock = tracker()
    a.begin("d", "answer", "task:t1")
    clock.t += STALE_S + 1
    assert a.snapshot("d") == {"type": "agent.activity", "working": False, "what": "reading", "count": 0}


@pytest.mark.parametrize("status", ["pending", "done", "failed"])
def test_task_hook(status):
    a, sent, _ = tracker()
    a.on_task({"id": "t1", "document_id": "d", "kind": "question", "status": "running"})
    assert sent[-1][1] == {"type": "agent.activity", "working": True, "what": "answer", "count": 1}
    a.on_task({"id": "t1", "document_id": "d", "kind": "question", "status": status})
    assert sent[-1][1]["working"] is False


def test_task_hook_other_kinds_are_task():
    a, sent, _ = tracker()
    a.on_task({"id": "t2", "document_id": "d", "kind": "offer", "status": "running"})
    assert sent[-1][1]["what"] == "task"


@pytest.fixture(autouse=True)
def _reset_module_tracker():
    yield
    activity.configure(None)
    activity._live.clear()
    activity._last.clear()
