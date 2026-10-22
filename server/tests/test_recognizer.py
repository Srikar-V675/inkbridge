import json
import threading
import time

import pytest

from inkbridge.recognizer import (
    BadResponse,
    MissingApiKey,
    RateLimited,
    Recognition,
    RecognizerTimeout,
)
from inkbridge.recognizer.gemini import DEFAULT_MODEL, GeminiRecognizer

PNG = b"\x89PNG fake"
OK = json.dumps({"text": "x squared", "latex": "x^2", "kind": "equation"})


class FakeTransport:
    """Stands in for the network: replays queued replies (a str, or an exception to raise)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, png, prompt, model):
        self.calls.append((png, prompt, model))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make(transport, **kw):
    sleeps = []
    kw.setdefault("min_interval", 0.0)
    rec = GeminiRecognizer(transport=transport, sleep=sleeps.append, **kw)
    return rec, sleeps


def test_success_returns_a_typed_recognition():
    t = FakeTransport(OK)
    rec, _ = make(t)
    out = rec(PNG, None)
    assert out == Recognition(text="x squared", latex="x^2", kind="equation", model=DEFAULT_MODEL)
    assert t.calls[0][0] == PNG and t.calls[0][2] == DEFAULT_MODEL


def test_json_in_a_code_fence_and_null_latex_are_accepted():
    rec, _ = make(
        FakeTransport('```json\n{"text": "hello", "latex": null, "kind": "handwriting"}\n```')
    )
    out = rec(PNG, None)
    assert (out.text, out.latex, out.kind) == ("hello", None, "handwriting")


def test_unknown_kind_falls_back_to_mixed():
    rec, _ = make(FakeTransport('{"text": "t", "latex": null, "kind": "banana"}'))
    assert rec(PNG, None).kind == "mixed"


def test_hint_reaches_the_prompt():
    t = FakeTransport(OK)
    rec, _ = make(t)
    rec(PNG, "a diagram of a loss curve")
    assert "a diagram of a loss curve" in t.calls[0][1]


def test_429_is_retried_with_backoff_then_succeeds():
    t = FakeTransport(RateLimited("429"), RateLimited("429"), OK)
    rec, sleeps = make(t, backoff=2.0)
    assert rec(PNG, None).text == "x squared"
    assert len(t.calls) == 3 and sleeps == [2.0, 4.0]


def test_429_gives_up_after_max_retries():
    t = FakeTransport(*[RateLimited("429")] * 3)
    rec, sleeps = make(t, max_retries=2, backoff=1.0)
    with pytest.raises(RateLimited):
        rec(PNG, None)
    assert len(t.calls) == 3 and sleeps == [1.0, 2.0]


def test_timeout_is_a_typed_error_and_not_retried_here():
    t = FakeTransport(RecognizerTimeout("slow"))
    rec, _ = make(t)
    with pytest.raises(RecognizerTimeout):
        rec(PNG, None)
    assert len(t.calls) == 1


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", '{"latex": "x"}', '{"text": 5}'])
def test_malformed_response_is_a_bad_response(reply):
    rec, _ = make(FakeTransport(reply))
    with pytest.raises(BadResponse):
        rec(PNG, None)


def test_missing_api_key_is_a_typed_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        GeminiRecognizer()


def test_api_key_never_appears_in_errors_or_repr(monkeypatch):
    secret = "AIza-super-secret-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    rec = GeminiRecognizer(
        transport=FakeTransport(RateLimited("429 for key " + secret)), max_retries=0
    )
    assert secret not in repr(rec)
    with pytest.raises(RateLimited) as err:
        rec(PNG, None)
    assert secret not in str(err.value)


def test_calls_are_spaced_by_min_interval():
    now = [100.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    rec = GeminiRecognizer(
        transport=FakeTransport(OK, OK), min_interval=4.0, sleep=sleep, clock=lambda: now[0]
    )
    rec(PNG, None)
    now[0] += 1.0
    rec(PNG, None)
    assert sleeps == [pytest.approx(3.0)]


def test_concurrent_calls_are_serialised():
    active, peak, lock = [0], [0], threading.Lock()

    def transport(png, prompt, model):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return OK

    rec = GeminiRecognizer(transport=transport, min_interval=0.0)
    threads = [threading.Thread(target=rec, args=(PNG, None)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 1
