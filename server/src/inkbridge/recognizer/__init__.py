"""Handwriting recognition: one swappable function from a chunk image to text, LaTeX and kind.

Recognition is a cache in front of a model (see INK-014); ink is the truth. Nothing here touches
the database, so tests and the worker use any callable matching `Recognizer`. There is no
module-level `recognize()`: the only caller is the opt-in worker, which owns the privacy gate
(decision 0017).
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

KINDS = ("handwriting", "equation", "diagram", "mixed")


@dataclass(frozen=True)
class Recognition:
    text: str
    latex: str | None
    kind: str
    model: str


class RecognizerError(Exception):
    """Base class: the worker retries these with backoff and never surfaces them to the editor,
    except `PermanentError` subclasses, which retrying cannot fix."""


class PermanentError(RecognizerError):
    """A configuration problem (missing or rejected key): the worker must stop, not retry."""


class RateLimited(RecognizerError):
    """The provider answered 429 (free-tier limits) or the subscription window is used up."""

    def __init__(self, msg: str = "", retry_after_s: float | None = None):
        super().__init__(msg)
        self.retry_after_s = retry_after_s


class ServiceUnavailable(RecognizerError):
    """The provider answered 503 (overloaded or down); every chunk would hit it too."""


class RecognizerTimeout(RecognizerError):
    """The provider did not answer in time."""


class BadResponse(RecognizerError):
    """The provider answered, but not with the JSON shape we asked for."""


class MissingApiKey(PermanentError):
    """GEMINI_API_KEY is not set."""


class InvalidApiKey(PermanentError):
    """The provider rejected the key (401/403, or 400 "API key not valid"): fix the key."""


class Recognizer(Protocol):
    def __call__(self, png: bytes, hint: str | None) -> Recognition: ...


_KIND_ALIASES = {"text": "handwriting", "math": "equation"}


def parse_reading(raw: str, model: str) -> Recognition:
    """Turn a model's JSON reply (optionally fenced, optionally a list) into a Recognition."""
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data: Any = json.loads(body)
    except (ValueError, RecursionError):
        raise BadResponse("model reply was not JSON") from None
    # Models sometimes wrap the object in a list (one item per line or block).
    items = data if isinstance(data, list) else [data]
    if not items or not all(isinstance(i, dict) and isinstance(i.get("text"), str) for i in items):
        raise BadResponse("model reply is missing a string 'text'")
    latexes = [i["latex"] for i in items if isinstance(i.get("latex"), str) and i["latex"]]
    raw_kind = items[0].get("kind")
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else None
    kind = _KIND_ALIASES.get(kind, kind) if kind else None
    return Recognition(
        text="\n".join(i["text"] for i in items),
        latex="\n".join(latexes) or None,
        kind=kind if kind in KINDS else "mixed",
        model=model,
    )


def make_recognizer() -> Recognizer:
    """The reader chosen by INKBRIDGE_RECOGNIZER (`gemini` default, or `claude`; INK-185)."""
    choice = os.environ.get("INKBRIDGE_RECOGNIZER", "gemini").strip().lower() or "gemini"
    if choice == "claude":
        from inkbridge.recognizer import claude

        return claude.default_recognizer()
    if choice != "gemini":
        logging.getLogger(__name__).warning("INKBRIDGE_RECOGNIZER=%r unknown; using gemini", choice)
    from inkbridge.recognizer import gemini

    return gemini.default_recognizer()
