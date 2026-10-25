import json
import threading
import time

import pytest

from inkbridge.recognizer import (
    BadResponse,
    InvalidApiKey,
    MissingApiKey,
    PermanentError,
    RateLimited,
    Recognition,
    RecognizerError,
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


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[1, 2]",
        '{"latex": "x"}',
        '{"text": 5}',
        "[" * 100_000 + "]" * 100_000,
    ],
)
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


def test_redacted_errors_do_not_chain_the_original_message():
    secret = "AIza-chained-secret"
    rec = GeminiRecognizer(
        api_key=secret,
        transport=FakeTransport(RateLimited("429 " + secret)),
        max_retries=0,
        min_interval=0.0,
    )
    with pytest.raises(RateLimited) as err:
        rec(PNG, None)
    assert err.value.__context__ is None and err.value.__cause__ is None


def test_invalid_key_is_its_own_non_retryable_type():
    t = FakeTransport(InvalidApiKey("401"))
    rec, sleeps = make(t)
    with pytest.raises(InvalidApiKey):
        rec(PNG, None)
    assert len(t.calls) == 1 and sleeps == []
    assert not issubclass(InvalidApiKey, RateLimited)


def test_a_single_item_list_reply_is_unwrapped():
    rec, _ = make(FakeTransport('[{"text": "hello", "latex": null, "kind": "handwriting"}]'))
    assert rec(PNG, None).text == "hello"


def test_a_multi_item_list_reply_is_joined():
    rec, _ = make(
        FakeTransport(
            '[{"text": "line one", "latex": null, "kind": "handwriting"},'
            ' {"text": "x^2", "latex": "x^2", "kind": "equation"}]'
        )
    )
    out = rec(PNG, None)
    assert out.text == "line one\nx^2" and out.latex == "x^2"


def test_kind_aliases_text_and_math_are_mapped():
    for given, expected in [("text", "handwriting"), ("math", "equation")]:
        rec, _ = make(FakeTransport(json.dumps({"text": "t", "latex": None, "kind": given})))
        assert rec(PNG, None).kind == expected


@pytest.mark.parametrize("kind", [["equation"], {"a": 1}, 3, None])
def test_a_non_string_kind_becomes_mixed_not_a_crash(kind):
    rec, _ = make(FakeTransport(json.dumps({"text": "t", "latex": None, "kind": kind})))
    assert rec(PNG, None).kind == "mixed"


def test_kind_is_matched_case_insensitively():
    rec, _ = make(FakeTransport('{"text": "t", "latex": null, "kind": " Equation "}'))
    assert rec(PNG, None).kind == "equation"


def test_key_problems_are_permanent_and_others_are_not():
    assert issubclass(MissingApiKey, PermanentError) and issubclass(InvalidApiKey, PermanentError)
    for retryable in (RateLimited, RecognizerTimeout, BadResponse):
        assert not issubclass(retryable, PermanentError)


def test_empty_gemini_model_env_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")
    rec, _ = make(FakeTransport(OK))
    assert rec.model == DEFAULT_MODEL


# The real Google transport, with the SDK call patched out: no network.


def google(monkeypatch, outcome):
    from google.genai import models

    def generate_content(self, **kw):
        if isinstance(outcome, BaseException):
            raise outcome
        return type("Reply", (), {"text": outcome})()

    monkeypatch.setattr(models.Models, "generate_content", generate_content)
    return GeminiRecognizer(
        api_key="test-key", max_retries=0, min_interval=0.0, sleep=lambda s: None
    )


def api_error(code, message="boom"):
    from google.genai import errors

    return errors.APIError(code, {"error": {"code": code, "message": message, "status": "X"}})


def test_google_transport_returns_the_reply_text(monkeypatch):
    assert google(monkeypatch, OK)(PNG, None).text == "x squared"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (api_error(429), RateLimited),
        (api_error(401), InvalidApiKey),
        (api_error(403), InvalidApiKey),
        (api_error(400, "API key not valid. Please pass a valid API key."), InvalidApiKey),
        (api_error(504, "Deadline exceeded"), RecognizerTimeout),
        (api_error(408), RecognizerTimeout),
        (api_error(404, "model not found"), RecognizerError),
    ],
)
def test_google_transport_maps_api_errors(monkeypatch, error, expected):
    with pytest.raises(expected) as err:
        google(monkeypatch, error)(PNG, None)
    assert type(err.value) is expected


def test_google_transport_maps_httpx_timeouts(monkeypatch):
    import httpx

    with pytest.raises(RecognizerTimeout):
        google(monkeypatch, httpx.ReadTimeout("read timed out"))(PNG, None)


def test_google_transport_redacts_the_key_from_api_messages(monkeypatch):
    with pytest.raises(RecognizerError) as err:
        google(monkeypatch, api_error(404, "bad key test-key"))(PNG, None)
    assert "test-key" not in str(err.value)
