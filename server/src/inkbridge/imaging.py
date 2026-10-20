"""Limits applied to what agents receive: image width and ink point count. Pure, no I/O."""

import io
from typing import Any

from PIL import Image

MAX_IMAGE_WIDTH = 1024
MAX_INK_POINTS = 5000


def cap_width(png: bytes, max_width: int = MAX_IMAGE_WIDTH) -> bytes:
    """Downscale a PNG to at most max_width px wide, keeping aspect ratio."""
    with Image.open(io.BytesIO(png)) as img:
        w, h = img.size
        if w <= max_width:
            return png
        out = io.BytesIO()
        img.resize((max_width, max(1, round(h * max_width / w))), Image.Resampling.LANCZOS).save(
            out, "PNG"
        )
    return out.getvalue()


def is_valid_png(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            return img.format == "PNG"
    except Exception:  # noqa: BLE001 - any decode failure means "not a usable PNG"
        return False


def _sample(items: list, k: int) -> list:
    """k evenly spaced items including first and last."""
    if k >= len(items):
        return items
    if k == 1:
        return items[:1]
    last = len(items) - 1
    return [items[round(j * last / (k - 1))] for j in range(k)]


def decimate_strokes(strokes: list[dict[str, Any]], max_points: int = MAX_INK_POINTS) -> list[dict]:
    """Reduce total points to <= max_points; each kept point keeps its pressure.

    Strokes keep their first and last point when the budget allows. If there are so many tiny
    strokes that even one point each would not fit, later strokes are dropped.
    """
    total = sum(len(s["points"]) for s in strokes)
    if total <= max_points:
        return strokes
    ratio = max_points / total
    for floor in (2, 1):
        keep = [min(len(s["points"]), max(floor, int(len(s["points"]) * ratio))) for s in strokes]
        if sum(keep) <= max_points:
            break
    out, used = [], 0
    for s, k in zip(strokes, keep, strict=True):
        if used + k > max_points:
            continue
        n = len(s["points"])
        idx = _sample(list(range(n)), k)
        pressures = s.get("pressures") or []
        out.append(
            {
                **s,
                "points": [s["points"][i] for i in idx],
                # a pressure list that does not pair 1:1 with the points cannot be sampled safely
                "pressures": [pressures[i] for i in idx] if len(pressures) == n else [],
            }
        )
        used += k
    return out
