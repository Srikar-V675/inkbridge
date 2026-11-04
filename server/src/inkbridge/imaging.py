"""Limits applied to what agents receive: image width and ink point count. Pure, no I/O."""

import io
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw, ImageFont

MAX_IMAGE_WIDTH = 1024
MAX_INK_POINTS = 5000
MIN_BOX_PX = 24  # an overview chunk box is never drawn shorter than this (INK-086)
MAX_OVERVIEW_IMAGES = 3  # per read_canvas call; the rest continues with offset
# INK-096: the browser exports crops at most 2048 px on the long side, so 4096 units keeps the
# scale >= 0.5; the element cap bounds the main-thread cost of one export. Mirrored in
# web/src/cropSync.ts (a test on each side pins the numbers).
MAX_READ_UNITS = 4096
MAX_CROP_ELEMENTS = 1500


def unreadable_reason(bounds: dict[str, float], element_count: int) -> str | None:
    """Why a chunk cannot be cropped or read at a useful scale, or None when it can."""
    w, h = bounds["width"], bounds["height"]
    if max(w, h) > MAX_READ_UNITS or element_count > MAX_CROP_ELEMENTS:
        return (
            f"too large to read ({round(w)}x{round(h)} units, {element_count} elements): "
            "split the chunk"
        )
    return None


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
    Labels use a font sized to the output width and are moved clear of each other.
    """
    if not chunks:
        return _png(Image.new("RGB", (min(max_width, 64), 64), "white"))
    x0, y0, x1, y1 = _union(chunks)
    width, height = x1 - x0, y1 - y0
    scale = _scale(width, height, max_width)
    size = (max(1, min(max_width, round(width * scale))), max(1, round(height * scale)))
    canvas = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(size[0])
    anchors = []
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
        anchors.append((c["id"], (left, top)))
    for text, pos in _place_labels(anchors, font):
        draw.text(pos, text, fill=(200, 0, 0), font=font)
    return _png(canvas)


def _font(out_width: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """A label font sized to the output: about 1/60 of its width, 12 to 28 px."""
    size = max(12, min(28, round(out_width / 60)))
    try:
        return ImageFont.load_default(size=size)
    except Exception:  # noqa: BLE001 - no FreeType: the tiny bitmap font beats a 500
        return ImageFont.load_default()


def _union(chunks: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    """Canvas bounds of the chunks, padded by OVERVIEW_PAD."""
    x0 = min(c["bounds"]["x"] for c in chunks) - OVERVIEW_PAD
    y0 = min(c["bounds"]["y"] for c in chunks) - OVERVIEW_PAD
    x1 = max(c["bounds"]["x"] + c["bounds"]["width"] for c in chunks) + OVERVIEW_PAD
    y1 = max(c["bounds"]["y"] + c["bounds"]["height"] for c in chunks) + OVERVIEW_PAD
    return x0, y0, x1, y1


def _scale(width: float, height: float, max_width: int) -> float:
    return min(1.0, max_width / width, (OVERVIEW_MAX_PIXELS / (width * height)) ** 0.5)


def plan_bands(
    chunks: list[dict[str, Any]],
    max_width: int = MAX_IMAGE_WIDTH,
    min_box: int = MIN_BOX_PX,
) -> list[list[dict[str, Any]]]:
    """Split chunks (in reading order) into consecutive bands that each render readable.

    A band grows while its union, fitted to max_width, still draws its smallest sized chunk at
    least min_box px tall. "Sized" means at least min_box canvas units tall: a dot or a bullet
    shorter than that is ignored when choosing bands, so it cannot cut its neighbours into
    one-chunk bands. Such a chunk may render below min_box px. A band always holds at least one
    chunk, so a chunk too small to ever reach min_box is shown alone, never upscaled.
    """
    bands: list[list[dict[str, Any]]] = []
    band: list[dict[str, Any]] = []
    for c in chunks:
        trial = [*band, c]
        x0, y0, x1, y1 = _union(trial)
        sized = [t["bounds"]["height"] for t in trial if t["bounds"]["height"] >= min_box]
        need = min(1.0, min_box / min(sized)) if sized else 0.0
        if band and _scale(x1 - x0, y1 - y0, max_width) < need:
            bands.append(band)
            band = [c]
        else:
            band = trial
    if band:
        bands.append(band)
    return bands


def _label_rect(font: Any, text: str, pos: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = font.getbbox(text)
    x, y = pos
    return (x + left, y + top, x + right, y + bottom)


def _place_labels(
    items: list[tuple[str, tuple[int, int]]], font: Any
) -> list[tuple[str, tuple[int, int]]]:
    """Move each label (text, box top-left) to the first spot that clashes with no placed label.

    Candidates, in order: above the box, inside its top-left corner, then below it and further
    down in steps. If every candidate clashes, the first one is used.
    """
    placed: list[tuple[int, int, int, int]] = []
    out: list[tuple[str, tuple[int, int]]] = []
    for text, (left, top) in items:
        _, text_top, _, text_bottom = font.getbbox(text)
        h = text_bottom - text_top
        ys = [top - h - 2, top + 2, top + h + 4, *(top + h + 4 + k * (h + 2) for k in (1, 2, 3))]
        candidates = [(max(0, left + 2), max(0, y)) for y in ys]
        chosen = candidates[0]
        for pos in candidates:
            r = _label_rect(font, text, pos)
            if not any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in placed):
                chosen = pos
                break
        placed.append(_label_rect(font, text, chosen))
        out.append((text, chosen))
    return out


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
