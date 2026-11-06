"""Server-side raster of chunk crops and canvas thumbnails (INK-120). Pure: elements in, PNG bytes out.

Not pixel-identical to Excalidraw's export: shapes are outlines only (no fills, so text inside
stays visible), one stroke colour per element, no hachure or roughness, and text uses Pillow's
bundled font. Pressure widens the freedraw stroke segment by segment. Drafts and deleted
elements are never drawn (they are not content). Decision 0065.
"""

import functools
import io
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from inkbridge.canvas.sketch import usable

MAX_CROP_SIDE = 2048  # px, long side of a crop
MAX_PIXELS = 4_000_000
CROP_PAD = 10  # canvas units around the ink
THUMB_MARGIN = 16
CHARCOAL = (30, 30, 30)
HEAD_LEN = 12  # arrowhead length, canvas units
HEAD_ANGLE = math.radians(25)
ROUND_CAP_FROM = 3  # px: thinner strokes need no round cap
ELLIPSE_STEPS = 48

Point = tuple[float, float]


def _drawable(elements: list[Any]) -> list[dict[str, Any]]:
    return [
        e
        for e in elements
        if usable(e)
        and not e.get("isDeleted")
        and not (e.get("customData") or {}).get("draft")
        and e.get("strokeColor") != "transparent"
    ]


def _colour(raw: Any) -> tuple[int, int, int]:
    if isinstance(raw, str) and raw.startswith("#"):
        h = raw[1:]
        try:
            if len(h) == 3:
                return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return CHARCOAL


def _width(base: float, scale: float, pressure: float | None) -> int:
    """Pixel width of a stroke segment; pressure 0.5 (or none) is 1.0x the base width."""
    p = 0.5 if pressure is None else min(1.0, max(0.0, pressure))
    return max(1, round(scale * base * (0.35 + 1.3 * p)))


@functools.lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except Exception:  # noqa: BLE001 - no FreeType: the tiny bitmap font beats a failure
        return ImageFont.load_default()


def _num(v: Any, default: float = 0.0) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default


def _spin(e: dict[str, Any]):
    """Rotation of canvas points around the element's centre."""
    angle = _num(e.get("angle"))
    cx = _num(e.get("x")) + _num(e.get("width")) / 2
    cy = _num(e.get("y")) + _num(e.get("height")) / 2
    if not angle:
        return lambda x, y: (x, y)
    cos, sin = math.cos(angle), math.sin(angle)
    return lambda x, y: (cx + (x - cx) * cos - (y - cy) * sin, cy + (x - cx) * sin + (y - cy) * cos)


def _head(tip: Point, other: Point) -> list[list[Point]]:
    """Two short lines at `tip` pointing back along the segment from `other`."""
    base = math.atan2(other[1] - tip[1], other[0] - tip[0])
    return [
        [
            tip,
            (
                tip[0] + HEAD_LEN * math.cos(base + s * HEAD_ANGLE),
                tip[1] + HEAD_LEN * math.sin(base + s * HEAD_ANGLE),
            ),
        ]
        for s in (1, -1)
    ]


def _geometry(e: dict[str, Any]) -> list[dict[str, Any]]:
    """Primitives in canvas units: polylines (with per-segment widths) and text boxes."""
    spin = _spin(e)
    x, y = _num(e.get("x")), _num(e.get("y"))
    w, h = _num(e.get("width")), _num(e.get("height"))
    colour = _colour(e.get("strokeColor"))
    base = _num(e.get("strokeWidth"), 2.0) or 2.0
    kind = e.get("type")
    if kind in ("freedraw", "line", "arrow") and e.get("points"):
        pts = [spin(x + p[0], y + p[1]) for p in e["points"]]
        if kind == "freedraw":
            pressures = e.get("pressures") or []
            widths = [
                pressures[i]
                if i < len(pressures) and isinstance(pressures[i], int | float)
                else None
                for i in range(1, len(pts))
            ]
            return [{"pts": pts, "base": base, "pressures": widths, "colour": colour}]
        lines = [{"pts": pts, "base": base, "pressures": None, "colour": colour}]
        if kind == "arrow" and len(pts) > 1:
            if e.get("endArrowhead") is not None:
                lines += [
                    {"pts": p, "base": base, "pressures": None, "colour": colour}
                    for p in _head(pts[-1], pts[-2])
                ]
            if e.get("startArrowhead") is not None:
                lines += [
                    {"pts": p, "base": base, "pressures": None, "colour": colour}
                    for p in _head(pts[0], pts[1])
                ]
        return lines
    if kind in ("rectangle", "diamond", "ellipse"):
        if kind == "rectangle":
            ring = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        elif kind == "diamond":
            ring = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        else:
            ring = [
                (
                    x + w / 2 + w / 2 * math.cos(2 * math.pi * k / ELLIPSE_STEPS),
                    y + h / 2 + h / 2 * math.sin(2 * math.pi * k / ELLIPSE_STEPS),
                )
                for k in range(ELLIPSE_STEPS)
            ]
        ring = [spin(*p) for p in ring]
        return [{"pts": [*ring, ring[0]], "base": base, "pressures": None, "colour": colour}]
    if kind == "text" and isinstance(e.get("text"), str) and e["text"]:
        size = _num(e.get("fontSize"), 20.0) or 20.0
        lines = e["text"].split("\n")
        if h <= 0:
            h = 1.25 * size * len(lines)
        corners = [spin(*p) for p in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
        return [
            {
                "text": lines,
                "size": size,
                "x": x,
                "y": y,
                "w": w,
                "align": e.get("textAlign"),
                "colour": colour,
                "origin": spin(x, y),
                "corners": corners,
            }
        ]
    return []


def _points_of(prims: list[dict[str, Any]]) -> list[Point]:
    out: list[Point] = []
    for p in prims:
        out += p["pts"] if "pts" in p else p["corners"]
    return out


def _paint(draw: ImageDraw.ImageDraw, prims: list[dict[str, Any]], px, scale: float) -> None:
    for p in prims:
        if "text" in p:
            size = max(8, round(p["size"] * scale))
            font = _font(size)
            line_h = 1.25 * p["size"] * scale
            ox, oy = px(*p["origin"])
            for n, line in enumerate(p["text"]):
                dx = 0.0
                if p["w"] and p["align"] in ("center", "right"):
                    try:
                        tw = draw.textlength(line, font=font)
                    except Exception:  # noqa: BLE001
                        tw = 0.0
                    free = p["w"] * scale - tw
                    dx = free / 2 if p["align"] == "center" else free
                draw.text((ox + dx, oy + n * line_h), line, fill=p["colour"], font=font)
            continue
        pts = [px(*q) for q in p["pts"]]
        pressures = p["pressures"]
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        for i in range(1, len(pts)):
            w = _width(
                p["base"],
                scale,
                pressures[i - 1] if pressures is not None and i - 1 < len(pressures) else None,
            )
            draw.line([pts[i - 1], pts[i]], fill=p["colour"], width=w)
            if w >= ROUND_CAP_FROM:
                r = w / 2
                for cx, cy in (pts[i - 1], pts[i]):
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=p["colour"])


def _prims(elements: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in _drawable(elements):
        try:
            out += _geometry(e)
        except (TypeError, ValueError, IndexError, KeyError):
            continue  # malformed in a way usable() could not see: skip the element
    return [p for p in out if _points_of([p])]


def _bounds(prims: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    pts = _points_of(prims)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def render_crop(
    elements: list[dict], *, max_side: int = MAX_CROP_SIDE, pad: int = CROP_PAD
) -> bytes | None:
    """PNG of these elements on white; None when nothing drawable is left (all deleted, draft or malformed)."""
    prims = _prims(elements)
    if not prims:
        return None
    x0, y0, x1, y1 = _bounds(prims)
    bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    scale = min(1.0, (max_side - 2 * pad) / max(bw, bh))
    w, h = round(bw * scale) + 2 * pad, round(bh * scale) + 2 * pad
    if w * h > MAX_PIXELS:  # only reachable with a small max_side cap raised by the caller
        scale *= math.sqrt(MAX_PIXELS / (w * h))
        w, h = round(bw * scale) + 2 * pad, round(bh * scale) + 2 * pad
    img = Image.new("RGB", (w, h), "white")
    _paint(
        ImageDraw.Draw(img),
        prims,
        lambda x, y: (pad + (x - x0) * scale, pad + (y - y0) * scale),
        scale,
    )
    return _png(img)


def render_thumbnail(elements: list[dict], *, width: int = 480, height: int = 320) -> bytes:
    """PNG of the whole canvas fitted inside width x height (aspect kept, centred on white, never scaled up past 1.0, 16 px margin). An empty canvas gives a blank white card of that size. INK-118 calls this with the scene's element list and caches the result."""
    img = Image.new("RGB", (width, height), "white")
    prims = _prims(elements)
    if prims:
        x0, y0, x1, y1 = _bounds(prims)
        bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        scale = min(1.0, (width - 2 * THUMB_MARGIN) / bw, (height - 2 * THUMB_MARGIN) / bh)
        ox = (width - bw * scale) / 2
        oy = (height - bh * scale) / 2
        _paint(
            ImageDraw.Draw(img),
            prims,
            lambda x, y: (ox + (x - x0) * scale, oy + (y - y0) * scale),
            scale,
        )
    return _png(img)
