"""Handwriting recognition: one swappable function from a chunk image to text, LaTeX and kind.

Recognition is a cache in front of a model (see INK-014); ink is the truth. Nothing here touches
the database, so tests and the worker use any callable matching `Recognizer`.
"""

from dataclasses import dataclass
from typing import Protocol

KINDS = ("handwriting", "equation", "diagram", "mixed")


@dataclass(frozen=True)
class Recognition:
    text: str
    latex: str | None
    kind: str
    model: str


class RecognizerError(Exception):
    """Base class: the worker retries these with backoff and never surfaces them to the editor."""


class RateLimited(RecognizerError):
    """The provider answered 429 (free-tier limits)."""


class RecognizerTimeout(RecognizerError):
    """The provider did not answer in time."""


class BadResponse(RecognizerError):
    """The provider answered, but not with the JSON shape we asked for."""


class MissingApiKey(RecognizerError):
    """GEMINI_API_KEY is not set."""


class InvalidApiKey(RecognizerError):
    """The provider rejected the key (401/403): retrying cannot help, fix the key."""


class Recognizer(Protocol):
    def __call__(self, png: bytes, hint: str | None) -> Recognition: ...


def recognize(png: bytes, hint: str | None = None) -> Recognition:
    """Recognise one chunk image with the default (Gemini) recognizer."""
    from inkbridge.recognizer.gemini import default_recognizer

    return default_recognizer()(png, hint)
