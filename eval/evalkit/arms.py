"""Input representations for E1: what the reader is shown for one chunk.

Payloads are built from the page's own elements, so token counts come from the actual payload.
Only the model's behaviour is simulated (see ArmNoisy, which lives beside the other readers).
Read-only: nothing here writes scenes or touches a hash; pressure is only read.
"""

import dataclasses
import math
import random
from dataclasses import dataclass
from typing import Any

from inkbridge.imaging import decimate_strokes

from .dataset import Chunk, Page
from .readers import NoisyReader, Reading

ARMS = ("image", "image+strokes", "strokes")
IMAGE_SCALE = 1.0  # fixed across arms
STROKE_WIDTH = 2  # fixed across arms (documented; the stroke text does not draw)
STROKE_TOKEN_BUDGET = 1500
PAD = 8  # canvas px around the chunk, as in the recognizer crop
PRICE_PER_MTOK_IN = (
    0.30  # PLACEHOLDER input price in USD per million tokens; the real run replaces it
)


@dataclass(frozen=True)
class Payload:
    arm: str  # the arm requested
    image_tokens: int  # 0 when no image is sent
    strokes: str | None  # compact stroke text, None when not sent
    stroke_tokens: int
    fell_back: bool = False  # image+strokes degraded to image only
    no_input: bool = False  # strokes arm with nothing to send

    @property
    def tokens(self) -> int:
        return self.image_tokens + self.stroke_tokens


def _hits(el: dict[str, Any], box: dict[str, float]) -> bool:
    if el.get("type") != "freedraw" or el.get("isDeleted"):
        return False
    if (el.get("customData") or {}).get("draft"):
        return False
    return (
        el["x"] < box["x"] + box["width"]
        and box["x"] < el["x"] + el["width"]
        and el["y"] < box["y"] + box["height"]
        and box["y"] < el["y"] + el["height"]
    )


def _stroke_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def _render(strokes: list[dict[str, Any]], box: dict[str, float]) -> str:
    lines = []
    for s in strokes:
        pressures = s["pressures"] or [0.5] * len(s["points"])
        lines.append(
            " ".join(
                f"{round(x)},{round(y)},{min(9, max(0, round(p * 9)))}"
                for (x, y), p in zip(s["points"], pressures, strict=True)
            )
        )
    return "\n".join(lines)


def strokes_payload(page: Page, chunk: Chunk, budget: int) -> str | None:
    """Offsets from chunk origin, pressure digit 0-9, decimated until it fits budget. None if no strokes."""
    box = chunk.box
    picked = [e for e in page.elements if _hits(e, box)]
    if not picked:
        return None
    strokes = [
        {
            "points": [[e["x"] + px - box["x"], e["y"] + py - box["y"]] for px, py in e["points"]],
            "pressures": list(e.get("pressures") or []),
        }
        for e in picked
    ]
    total_points = sum(len(s["points"]) for s in strokes)
    max_points = min(total_points, budget * 4 // 8)
    floor = len(strokes)  # one point per stroke is the least we keep
    while True:
        text = _render(decimate_strokes(strokes, max(max_points, floor)), box)
        if _stroke_tokens(text) <= budget or max_points <= floor:
            return text
        max_points = max(floor, max_points // 2)


def image_tokens(chunk: Chunk) -> int:
    w = (chunk.box["width"] + 2 * PAD) * IMAGE_SCALE
    h = (chunk.box["height"] + 2 * PAD) * IMAGE_SCALE
    return math.ceil(w * h / 750)


def build_payload(page, chunk, arm, budget: int = STROKE_TOKEN_BUDGET) -> Payload:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    img = image_tokens(chunk)
    if arm == "image":
        return Payload(arm, img, None, 0)
    text = strokes_payload(page, chunk, budget)
    if arm == "image+strokes":
        if text is None or _stroke_tokens(text) > budget:
            return Payload(arm, img, None, 0, fell_back=True)
        return Payload(arm, img, text, _stroke_tokens(text))
    # strokes only: no image to fall back to; drop trailing strokes until it fits the budget
    if text is None:
        return Payload(arm, 0, None, 0, no_input=True)
    lines = text.split("\n")
    while lines and _stroke_tokens("\n".join(lines)) > budget:
        lines.pop()
    if not lines:
        return Payload(arm, 0, None, 0, no_input=True)
    kept = "\n".join(lines)
    return Payload(arm, 0, kept, _stroke_tokens(kept))


def cost_usd(tokens: int) -> float:
    return tokens * PRICE_PER_MTOK_IN / 1e6


def arm_read(reader: Any, page: Page, chunk: Chunk, payload: Payload) -> Reading:
    """Read one chunk under one arm. A reader with read_arm(page, chunk, payload) sees the payload
    itself. Any other reader gets only the page and chunk, so its tokens and cost are the payload's
    (the simulated path); its latency is whatever it reports (0 for the simulated readers)."""
    if payload.no_input:
        return Reading(text="")
    read_arm = getattr(reader, "read_arm", None)
    if read_arm is not None:
        return read_arm(page, chunk, payload)
    r = reader.read(page, chunk)
    return dataclasses.replace(r, tokens=payload.tokens, cost_usd=cost_usd(payload.tokens))


class ArmNoisy:
    """Simulated reader for the arms: each arm corrupts text at its own rate (self-test only).
    A fallen-back image+strokes payload is read at the image rate, since that is what it saw."""

    name = "arms-noisy"

    def __init__(self, rates: dict[str, float]):
        unknown = set(rates) - set(ARMS)
        if unknown:
            raise ValueError(f"unknown arms: {sorted(unknown)}")
        missing = set(ARMS) - set(rates)
        if missing:
            raise ValueError(f"missing rates for arms: {sorted(missing)}")
        self.rates = dict(rates)

    def read_arm(self, page: Page, chunk: Chunk, payload: Payload) -> Reading:
        if payload.no_input:
            return Reading(text="")
        arm = "image" if payload.fell_back else payload.arm
        rng = random.Random(f"{arm}:{page.id}:{chunk.id}")
        corrupt = NoisyReader(self.rates[arm])._corrupt
        text = corrupt(chunk.text, rng)
        latex = corrupt(chunk.latex, rng) if chunk.latex else None
        return Reading(
            text=text,
            latex=latex,
            tokens=payload.tokens,
            cost_usd=cost_usd(payload.tokens),
        )


def parse_arm_rates(spec: str) -> dict[str, float]:
    """'image=0.05,image+strokes=0.02,strokes=0.2' -> {arm: rate}. Unknown arms are rejected."""
    rates: dict[str, float] = {}
    for part in filter(None, spec.split(",")):
        arm, _, rate = part.partition("=")
        if arm not in ARMS or not rate:
            raise ValueError(f"bad arm rate '{part}': expected ARM=RATE with ARM in {ARMS}")
        rates[arm] = float(rate)
    return rates
