"""Pluggable readers: oracle, noisy (self-test) and the gated Gemini reader."""

import importlib
import io
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .dataset import Chunk, Dataset, Page


class GateError(RuntimeError):
    """The Gemini reader refused to start (privacy gate)."""


@dataclass(frozen=True)
class Reading:
    text: str
    latex: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0


class Reader(Protocol):
    name: str

    def read(self, page: Page, chunk: Chunk) -> Reading: ...


class OracleReader:
    name = "oracle"

    def read(self, page: Page, chunk: Chunk) -> Reading:
        return Reading(text=chunk.text, latex=chunk.latex)


class NoisyReader:
    """Deterministic character corruption: each char is dropped or replaced with probability rate."""

    def __init__(self, rate: float, seed: int = 0):
        self.rate = rate
        self.seed = seed
        self.name = f"noisy:{rate:g}"

    def _corrupt(self, text: str, rng: random.Random) -> str:
        out = []
        for ch in text:
            if rng.random() < self.rate:
                if rng.random() < 0.5:
                    out.append("#")  # replace
                # else drop
            else:
                out.append(ch)
        return "".join(out)

    def read(self, page: Page, chunk: Chunk) -> Reading:
        rng = random.Random(f"{self.seed}:{page.id}:{chunk.id}")
        latex = self._corrupt(chunk.latex, rng) if chunk.latex else None
        return Reading(text=self._corrupt(chunk.text, rng), latex=latex)


class _GeminiReader:
    name = "gemini"

    def __init__(self, recognizer: Any):
        self._recognizer = recognizer

    def read(self, page: Page, chunk: Chunk) -> Reading:
        from PIL import Image

        assert page.png is not None
        pad = 8
        b = chunk.box
        image = Image.open(io.BytesIO(page.png))
        crop = image.crop(
            (
                max(int(b["x"]) - pad, 0),
                max(int(b["y"]) - pad, 0),
                min(int(b["x"] + b["width"]) + pad, image.width),
                min(int(b["y"] + b["height"]) + pad, image.height),
            )
        )
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        start = time.monotonic()
        rec = self._recognizer(buf.getvalue(), chunk.kind)
        latency = time.monotonic() - start
        return Reading(
            text=rec.text,
            latex=rec.latex,
            tokens=getattr(rec, "tokens", 0) or 0,
            cost_usd=getattr(rec, "cost_usd", 0.0) or 0.0,
            latency_s=latency,
        )


def check_model_gate(dataset: Dataset, allow_model: bool, who: str) -> None:
    """One gate for every reader that may reach a model. Gemini's free tier trains on content, so
    such a reader only ever sees pages declared as test pages, and only when the caller opts in.
    `test_pages_only` is the user's own assertion: they must not set it for personal pages."""
    if not allow_model:
        raise GateError(f"{who} reader needs --allow-model")
    if not dataset.test_pages_only:
        raise GateError("dataset manifest does not declare test_pages_only: true")
    if dataset.synthetic:
        raise GateError("synthetic fixtures have no handwriting: refusing a pointless model call")


def load_gemini_reader(dataset: Dataset, allow_model: bool) -> Reader:
    """The only place the eval can reach Gemini."""
    check_model_gate(dataset, allow_model, "gemini")
    if not os.environ.get("GEMINI_API_KEY"):
        raise GateError("GEMINI_API_KEY is not set")
    missing = [p.id for p in dataset.pages if p.png is None]
    if missing:
        raise GateError(f"pages without page.png: {missing}")
    from inkbridge.recognizer.gemini import default_recognizer  # lazy: no model client at import

    return _GeminiReader(default_recognizer())


def load_reader(spec: str, dataset: Dataset, allow_model: bool = False) -> Reader:
    if spec == "oracle":
        return OracleReader()
    if spec.startswith("noisy:"):
        return NoisyReader(float(spec.split(":", 1)[1]))
    if spec == "gemini":
        return load_gemini_reader(dataset, allow_model)
    if ":" in spec:
        # A custom reader may call any model: same gate as gemini (minus the Gemini specifics).
        check_model_gate(dataset, allow_model, "custom")
        module, attr = spec.split(":", 1)
        return getattr(importlib.import_module(module), attr)
    raise ValueError(f"unknown reader spec: {spec}")
