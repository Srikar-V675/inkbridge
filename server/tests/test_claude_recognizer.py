"""INK-185: Claude Haiku reader through a persistent `claude -p` stream-json process. No real claude."""

import json
import logging
import queue

import pytest

from inkbridge.recognizer import (
    PermanentError,
    RateLimited,
    Recognition,
    RecognizerError,
    RecognizerTimeout,
    make_recognizer,
)
from inkbridge.recognizer.claude import ClaudeNotFound, ClaudeRecognizer

PNG = b"\x89PNG fake"
GOOD = {
    "type": "result",
    "is_error": False,
    "result": '```json\n{"text":"hello","latex":null,"kind":"handwriting"}\n```',
    "usage": {"input_tokens": 5, "output_tokens": 3},
    "total_cost_usd": 0.001,
}


class FakeStdin:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class FakeProc:
    """stdout yields the scripted lines, then (unless `hang`) ends."""

    def __init__(self, replies=(), hang=False):
        self.stdin = FakeStdin()
        self.killed = False
        self._q: queue.Queue = queue.Queue()
        for r in replies:
            self._q.put(r if isinstance(r, str) else json.dumps(r))
        if not hang:
            self._q.put(None)
        self.stdout = iter(self._q.get, None)

    def poll(self):
        return 1 if self.killed else None

    def kill(self):
        self.killed = True
        self._q.put(None)

    def wait(self, timeout=None):
        return 0


def spawner(*procs):
    made = list(procs)
    spawned: list[FakeProc] = []

    def spawn():
        p = made.pop(0)
        spawned.append(p)
        return p

    spawn.spawned = spawned
    return spawn


def test_reads_json_reply():
    p = FakeProc(["not json", {"type": "assistant"}, GOOD])
    r = ClaudeRecognizer(spawn=spawner(p))
    assert r(PNG, None) == Recognition("hello", None, "handwriting", "claude-haiku")
    sent = json.loads(p.stdin.lines[0])
    assert sent["type"] == "user" and sent["message"]["content"][0]["type"] == "image"
    assert p.stdin.lines[0].endswith("\n")


def test_process_reused_then_reset():
    a, b = FakeProc([GOOD, GOOD]), FakeProc([GOOD])
    spawn = spawner(a, b)
    r = ClaudeRecognizer(spawn=spawn, max_requests=2)
    for _ in range(3):
        r(PNG, None)
    assert len(spawn.spawned) == 2 and a.killed


@pytest.mark.parametrize("text", ["5-hour usage limit reached", "Rate limit exceeded"])
def test_is_error_rate_limit_raises_RateLimited(text):
    bad = {"type": "result", "is_error": True, "result": text}
    a, b = FakeProc([bad]), FakeProc([GOOD])
    spawn = spawner(a, b)
    r = ClaudeRecognizer(spawn=spawn)
    with pytest.raises(RateLimited):
        r(PNG, None)
    assert a.killed
    assert r(PNG, None).text == "hello" and len(spawn.spawned) == 2


def test_other_is_error_raises_recognizer_error_not_rate_limited():
    bad = {"type": "result", "is_error": True, "result": "boom"}
    r = ClaudeRecognizer(spawn=spawner(FakeProc([bad])))
    with pytest.raises(RecognizerError) as e:
        r(PNG, None)
    assert not isinstance(e.value, RateLimited)


def test_resets_at_sets_retry_after():
    import time

    ev = {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": int(time.time()) + 900}}
    bad = {"type": "result", "is_error": True, "result": "usage limit reached"}
    r = ClaudeRecognizer(spawn=spawner(FakeProc([ev, bad])))
    with pytest.raises(RateLimited) as e:
        r(PNG, None)
    assert e.value.retry_after_s is not None and 800 < e.value.retry_after_s <= 900


def test_eof_raises_and_respawns():
    a, b = FakeProc([]), FakeProc([GOOD])
    spawn = spawner(a, b)
    r = ClaudeRecognizer(spawn=spawn)
    with pytest.raises(RecognizerError):
        r(PNG, None)
    assert r(PNG, None).text == "hello" and len(spawn.spawned) == 2


def test_timeout_raises():
    p = FakeProc([], hang=True)
    r = ClaudeRecognizer(spawn=spawner(p), timeout=0.05)
    with pytest.raises(RecognizerTimeout):
        r(PNG, None)
    assert p.killed


def test_missing_binary_is_permanent():
    def spawn():
        raise FileNotFoundError("claude")

    with pytest.raises(PermanentError) as e:
        ClaudeRecognizer(spawn=spawn)(PNG, None)
    assert isinstance(e.value, ClaudeNotFound)


def test_usage_logged(caplog):
    r = ClaudeRecognizer(spawn=spawner(FakeProc([GOOD, GOOD])))
    with caplog.at_level(logging.INFO, logger="inkbridge.recognizer.usage"):
        r(PNG, None)
        r(PNG, None)
    msgs = [m.getMessage() for m in caplog.records if m.name == "inkbridge.recognizer.usage"]
    assert "claude read #1 in=5 out=3" in msgs[0] and "#2" in msgs[1]


def test_make_recognizer_selects(monkeypatch):
    from inkbridge.recognizer import claude, gemini

    sentinel_c, sentinel_g = object(), object()
    monkeypatch.setattr(claude, "ClaudeRecognizer", lambda: sentinel_c)
    monkeypatch.setattr(claude, "_default", None)
    monkeypatch.setattr(gemini, "default_recognizer", lambda: sentinel_g)
    monkeypatch.setenv("INKBRIDGE_RECOGNIZER", "claude")
    assert make_recognizer() is sentinel_c
    assert make_recognizer() is sentinel_c  # singleton
    monkeypatch.setenv("INKBRIDGE_RECOGNIZER", "gemini")
    assert make_recognizer() is sentinel_g
    monkeypatch.setenv("INKBRIDGE_RECOGNIZER", "nonsense")
    assert make_recognizer() is sentinel_g
    monkeypatch.delenv("INKBRIDGE_RECOGNIZER")
    assert make_recognizer() is sentinel_g


