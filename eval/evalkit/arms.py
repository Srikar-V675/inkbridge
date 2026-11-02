"""Input representations for E1: what the reader is shown for one chunk.

Payloads are built from the page's own elements, so token counts come from the actual payload.
Only the model's behaviour is simulated (see ArmNoisy, which lives beside the other readers).
Read-only: nothing here writes scenes or touches a hash; pressure is only read.
"""

import math
from dataclasses import dataclass
from typing import Any

from inkbridge.imaging import decimate_strokes

from .dataset import Chunk, Page

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
