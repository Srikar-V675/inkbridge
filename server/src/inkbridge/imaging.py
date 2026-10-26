"""Limits applied to what agents receive: image width and ink point count. Pure, no I/O."""

import io
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw

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


OVERVIEW_PAD = 16  # canvas px around the chunks
OVERVIEW_MAX_PIXELS = 16_000_000  # about 48 MB as RGB, whatever the canvas's shape
_STALE = (230, 140, 0)
_BOX = (120, 120, 120)


def overview(
    chunks: list[dict[str, Any]],
    load: Callable[[str], bytes | None],
    max_width: int = MAX_IMAGE_WIDTH,
) -> bytes:
    """Composite PNG of chunk crops placed at their canvas bounds, each labelled with its id.

    `chunks` items carry `id`, `bounds` and `png_stale`; `load(id)` returns a chunk's crop bytes or
    None, and is called one chunk at a time so only one crop is in memory. A chunk without a
    decodable crop is drawn as a grey box; a stale crop gets an orange frame because it may not
    match the ink. Transparent crops are flattened onto white. The image is never scaled up, at
    most max_width wide and at most OVERVIEW_MAX_PIXELS in area, so a tall canvas stays small.
    """
    if not chunks:
        return _png(Image.new("RGB", (min(max_width, 64), 64), "white"))
    x0 = min(c["bounds"]["x"] for c in chunks) - OVERVIEW_PAD
    y0 = min(c["bounds"]["y"] for c in chunks) - OVERVIEW_PAD
    x1 = max(c["bounds"]["x"] + c["bounds"]["width"] for c in chunks) + OVERVIEW_PAD
    y1 = max(c["bounds"]["y"] + c["bounds"]["height"] for c in chunks) + OVERVIEW_PAD
    width, height = x1 - x0, y1 - y0
    scale = min(1.0, max_width / width, (OVERVIEW_MAX_PIXELS / (width * height)) ** 0.5)
    size = (max(1, min(max_width, round(width * scale))), max(1, round(height * scale)))
    canvas = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(canvas)
    for c in chunks:
        b = c["bounds"]
        left, top = round((b["x"] - x0) * scale), round((b["y"] - y0) * scale)
        w, h = max(1, round(b["width"] * scale)), max(1, round(b["height"] * scale))
        crop = _decode(load(c["id"]), (w, h))
        if crop is not None:
            canvas.paste(crop, (left, top))
        if crop is None or c.get("png_stale"):
            draw.rectangle(
                (left, top, left + w, top + h), outline=_STALE if crop else _BOX, width=1
            )
        draw.text((left + 2, max(0, top - 11)), c["id"], fill=(200, 0, 0))
    return _png(canvas)


def _decode(png: bytes | None, size: tuple[int, int]) -> Image.Image | None:
    """The crop resized to `size` on white, or None if it is missing or unreadable."""
    if not png:
        return None
    try:
        with Image.open(io.BytesIO(png)) as img:
            img.thumbnail((size[0] * 2, size[1] * 2))  # shrink early: cheap, bounded memory
            rgba = img.convert("RGBA")
    except Exception:  # noqa: BLE001 - an unreadable crop is drawn as a box instead
        return None
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return flat.resize(size, Image.Resampling.LANCZOS)


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
