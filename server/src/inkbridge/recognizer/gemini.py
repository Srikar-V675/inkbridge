"""Gemini Flash-Lite (free tier) recognizer. Free-tier content may be used for training:
only send test and eval pages, never personal notes."""

import json
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from inkbridge.recognizer import (
    KINDS,
    BadResponse,
    InvalidApiKey,
    MissingApiKey,
    RateLimited,
    Recognition,
    RecognizerError,
    RecognizerTimeout,
)

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

PROMPT = (
    "Transcribe the handwriting in this image. Reply with JSON only: "
    '{"text": plain-text reading, "latex": LaTeX for any maths or null, '
    '"kind": one of "handwriting", "equation", "diagram", "mixed"}. '
    "Do not add commentary."
)

Transport = Callable[[bytes, str, str], str]  # (png, prompt, model) -> raw response text


class GeminiRecognizer:
    """Calls are serialised and spaced by `min_interval` to stay inside free-tier rate limits."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        *,
        transport: Transport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 2.0,
        min_interval: float = 4.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._key = api_key or os.environ.get("GEMINI_API_KEY")
        if transport is None and not self._key:
            raise MissingApiKey("GEMINI_API_KEY is not set (see .env.example)")
        self.model = model
        self._transport = transport or self._google_transport(timeout)
        self._max_retries, self._backoff, self._min_interval = max_retries, backoff, min_interval
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._last_call: float | None = None

    def __repr__(self) -> str:  # never include the key
        return f"GeminiRecognizer(model={self.model!r})"

    def __call__(self, png: bytes, hint: str | None) -> Recognition:
        prompt = PROMPT if not hint else f"{PROMPT}\nContext hint: {hint}"
        with self._lock:
            raw = self._send(png, prompt)
        return self._parse(raw)

    def _send(self, png: bytes, prompt: str) -> str:
        for attempt in range(self._max_retries + 1):
            self._space_calls()
            try:
                return self._transport(png, prompt, self.model)
            except RateLimited as e:
                failure: RecognizerError = e
                retry = attempt < self._max_retries
            except RecognizerError as e:
                failure, retry = e, False
            if not retry:
                # Raised outside the except block so no chained context keeps the raw message.
                raise type(failure)(self._redact(str(failure)))
            self._sleep(self._backoff * 2**attempt)
        raise AssertionError("unreachable")

    def _space_calls(self) -> None:
        if self._last_call is not None and self._min_interval:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _redact(self, message: str) -> str:
        return message.replace(self._key, "***") if self._key else message

    def _parse(self, raw: str) -> Recognition:
        body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            data: Any = json.loads(body)
        except ValueError:
            raise BadResponse("model reply was not JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise BadResponse("model reply is missing a string 'text'")
        latex = data.get("latex")
        kind = data.get("kind")
        return Recognition(
            text=data["text"],
            latex=latex if isinstance(latex, str) and latex else None,
            kind=kind if kind in KINDS else "mixed",
            model=self.model,
        )

    def _google_transport(self, timeout: float) -> Transport:
        from google import genai
        from google.genai import errors, types

        client = genai.Client(
            api_key=self._key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

        def send(png: bytes, prompt: str, model: str) -> str:
            try:
                reply = client.models.generate_content(
                    model=model,
                    contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
            except errors.APIError as e:
                if e.code == 429:
                    raise RateLimited("Gemini rate limit (429)") from None
                if e.code in (401, 403):
                    raise InvalidApiKey(f"Gemini rejected the API key ({e.code})") from None
                raise RecognizerError(f"Gemini error {e.code}") from None
            except Exception as e:  # noqa: BLE001 - httpx timeouts surface as several types
                if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower():
                    raise RecognizerTimeout("Gemini request timed out") from None
                raise RecognizerError(f"Gemini request failed: {type(e).__name__}") from None
            return reply.text or ""

        return send


_default: GeminiRecognizer | None = None
_default_lock = threading.Lock()


def default_recognizer() -> GeminiRecognizer:
    global _default
    with _default_lock:
        if _default is None:
            _default = GeminiRecognizer()
        return _default
