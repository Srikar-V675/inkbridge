"""Server-side raster of chunk crops and canvas thumbnails (INK-120). Pure: elements in, PNG bytes out.

Not pixel-identical to Excalidraw's export: shapes are outlines only (no fills, so text inside
stays visible), one stroke colour per element, no hachure or roughness, and text uses Pillow's
bundled font. Pressure widens the freedraw stroke segment by segment. Drafts and deleted
elements are never drawn (they are not content). Decision 0065.

Thumbnails are a separate look (decision 0070): 960 x 640 on the panel colour, with a stroke floor
and tiny text drawn as bars. They show the centre chunk of the canvas when the caller passes the
chunk boxes (INK-179, decision 0084); the 0070 fit to the body of the ink without far strays is
the fallback. Crops keep the plain style above.
"""

import functools
import io
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from inkbridge.canvas.sketch import usable
from inkbridge.canvas.thumb_focus import Box, choose_focus

MAX_CROP_SIDE = 2048  # px, long side of a crop
MAX_PIXELS = 4_000_000
CROP_PAD = 10  # canvas units around the ink
THUMB_MARGIN = 16
THUMB_REVISION = 3  # bump when the look changes: it is part of the cache key and the ETag
# 3: shows the centre chunk (decision 0084)
FOCUS_MAX_SCALE = 3.0  # card px per canvas unit when a chunk is shown (the whole fit keeps 1.0)
FOCUS_SLACK = 0.05  # primitives within this share (+4 units) outside the chunk box still belong
THUMB_BG = (234, 228, 215)  # DESIGN.md `panel`, the home card colour
CARD_W = 480  # logical card width; the PNG is rendered at width / CARD_W times that
THUMB_MIN_STROKE = 2.0  # card px
THUMB_FREEDRAW_MIN = 2.5
FREEDRAW_BOOST = 1.25
THUMB_STEP = 0.8  # card px: drop polyline points closer than this
GREEK_BELOW = 5.0  # card px: text with a smaller font is drawn as bars
REACH = 6.0  # a primitive within REACH x (median distance from the median centre) still counts
STRAY_SHARE = 0.10  # far primitives are dropped only when they are at most this share of all
STRAY_FLOOR = 2  # ... or at most this many (a lone stray beside a tiny sketch still drops)
CHARCOAL = (30, 30, 30)
HEAD_LEN = 12  # arrowhead length, canvas units
HEAD_ANGLE = math.radians(25)
ROUND_CAP_FROM = 3  # px: thinner strokes need no round cap
ELLIPSE_STEPS = 48

Point = tuple[float, float]


@dataclass(frozen=True)
class _Style:
    min_w: int = 1
    free_min: int = 1
    boost: float = 1.0
    step: float = 0.0
    greek: float = 0.0  # px; 0 = never


CROP_STYLE = _Style()


def _thumb_style(k: float) -> _Style:
    return _Style(
        min_w=round(THUMB_MIN_STROKE * k),
        free_min=round(THUMB_FREEDRAW_MIN * k),
        boost=FREEDRAW_BOOST,
        step=THUMB_STEP * k,
        greek=GREEK_BELOW * k,
    )


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


def _width(
    base: float, scale: float, pressure: float | None, floor: int = 1, boost: float = 1.0
) -> int:
    """Pixel width of a stroke segment; pressure 0.5 (or none) is 1.0x the base width."""
    p = 0.5 if pressure is None else min(1.0, max(0.0, pressure))
    return max(floor, round(boost * scale * base * (0.35 + 1.3 * p)))


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
            return [{"pts": pts, "base": base, "pressures": widths, "colour": colour, "free": True}]
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


def _decimate(pts: list[Point], step: float) -> list[int]:
    """Indexes of the points to keep: each at least `step` px from the last kept one, and the last."""
    kept = [0]
    for i in range(1, len(pts)):
        if (
            i == len(pts) - 1
            or math.hypot(pts[i][0] - pts[kept[-1]][0], pts[i][1] - pts[kept[-1]][1]) >= step
        ):
            kept.append(i)
    return kept


def _paint(
    draw: ImageDraw.ImageDraw,
    prims: list[dict[str, Any]],
    px,
    scale: float,
    style: _Style = CROP_STYLE,
) -> None:
    for p in prims:
        if "text" in p:
            size_px = p["size"] * scale
            line_h = 1.25 * size_px
            ox, oy = px(*p["origin"])
            if style.greek and size_px < style.greek:
                for n, line in enumerate(p["text"]):
                    if not line.strip():
                        continue
                    length = min(0.5 * size_px * len(line), p["w"] * scale if p["w"] else math.inf)
                    y = oy + n * line_h + 0.5 * size_px
                    width = max(style.min_w, round(0.25 * size_px))
                    draw.line([(ox, y), (ox + length, y)], fill=p["colour"], width=width)
                continue
            font = _font(max(8, round(size_px)))
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
        free = bool(p.get("free"))
        floor = style.free_min if free else style.min_w
        boost = style.boost if free else 1.0
        kept = _decimate(pts, style.step) if style.step else list(range(len(pts)))
        for j in range(1, len(kept)):
            a, b = kept[j - 1], kept[j]
            i = b  # the segment ends at point b; its pressure is the one stored for that point
            w = _width(
                p["base"],
                scale,
                pressures[i - 1] if pressures is not None and i - 1 < len(pressures) else None,
                floor,
                boost,
            )
            draw.line([pts[a], pts[b]], fill=p["colour"], width=w)
            if w >= ROUND_CAP_FROM:
                r = w / 2
                for cx, cy in (pts[a], pts[b]):
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=p["colour"])


def _finite(p: dict[str, Any]) -> bool:
    """A primitive with points, none of them NaN or infinite (a NaN angle must not move the fit)."""
    pts = _points_of([p])
    return bool(pts) and all(math.isfinite(c) for pt in pts for c in pt)


def _prims(elements: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in _drawable(elements):
        try:
            out += _geometry(e)
        except (TypeError, ValueError, IndexError, KeyError):
            continue  # malformed in a way usable() could not see: skip the element
    return [p for p in out if _finite(p)]


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


def _median(values: list[float]) -> float:
    v = sorted(values)
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2


def _fit_box(prims: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Bounds of the main body of the ink: the whole box, minus far strays (they clip).

    A primitive counts when its centre is within REACH x max(MAD, median primitive size) of the
    median centre on both axes, so a handful of strays cannot move the frame however few strokes
    the page has. Primitives outside that reach are dropped only when they are strays: at most
    max(STRAY_FLOOR, STRAY_SHARE of all primitives). A bigger far group is a real second cluster
    and the fit covers everything.
    """
    boxes = [_bounds([p]) for p in prims]
    cx = [(b[0] + b[2]) / 2 for b in boxes]
    cy = [(b[1] + b[3]) / 2 for b in boxes]
    size = _median([max(b[2] - b[0], b[3] - b[1]) for b in boxes])
    limits = []
    for axis in (cx, cy):
        med = _median(axis)
        limits.append((med, REACH * max(_median([abs(c - med) for c in axis]), size, 1.0)))
    keep = [
        p
        for p, x, y in zip(prims, cx, cy, strict=True)
        if abs(x - limits[0][0]) <= limits[0][1] and abs(y - limits[1][0]) <= limits[1][1]
    ]
    if len(prims) - len(keep) > max(STRAY_FLOOR, int(STRAY_SHARE * len(prims))):
        return _bounds(prims)
    return _bounds(keep or prims)


def _touches(p: dict[str, Any], px, w: int, h: int) -> bool:
    """True when the primitive's mapped bounds meet the frame (keeps far strays away from PIL)."""
    x0, y0, x1, y1 = _bounds([p])
    a, b = px(x0, y0), px(x1, y1)
    return (
        max(a[0], b[0]) >= 0
        and min(a[0], b[0]) <= w
        and max(a[1], b[1]) >= 0
        and min(a[1], b[1]) <= h
    )


def _chunk_box(c: Any) -> Box | None:
    try:
        x, y, w, h = (float(c[k]) for k in ("x", "y", "width", "height"))
    except (TypeError, KeyError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w < 0 or h < 0:
        return None
    return x, y, x + w, y + h


def _focus(prims: list[dict[str, Any]], chunks: list[Any]) -> list[dict[str, Any]]:
    """The primitives of the centre chunk (decision 0084), or [] when nothing qualifies."""
    boxes = [_bounds([p]) for p in prims]
    chunk_boxes = [b for b in map(_chunk_box, chunks) if b is not None]
    focus = choose_focus(boxes, chunk_boxes, _fit_box(prims))
    if focus is None:
        return []
    slack = FOCUS_SLACK * max(focus[2] - focus[0], focus[3] - focus[1]) + 4.0
    return [
        p
        for p, b in zip(prims, boxes, strict=True)
        if focus[0] - slack <= (b[0] + b[2]) / 2 <= focus[2] + slack
        and focus[1] - slack <= (b[1] + b[3]) / 2 <= focus[3] + slack
    ]


def render_thumbnail(
    elements: list[dict], *, width: int = 960, height: int = 640, chunks: list[dict] | None = None
) -> bytes:
    """PNG of the canvas on the panel colour (decision 0070): 960 x 640, shown at 480 x 320.

    With `chunks` (bbox dicts {x, y, width, height} of the active chunks, possibly empty) it shows
    the centre chunk, large (decision 0084): up to FOCUS_MAX_SCALE card px per unit. Without
    `chunks`, or when no primitive falls in the chosen box, it falls back to the whole-canvas fit:
    the body of the ink (far strays clip), 1 canvas unit at most 1 card px. A 16 card px margin,
    strokes at least 2 card px, tiny text as bars. An empty or draft-only canvas is the blank
    panel colour. INK-118 calls this with the scene's element list and caches the result.
    """
    k = width / CARD_W
    img = Image.new("RGB", (width, height), THUMB_BG)
    prims = _prims(elements)
    cap, focused = k, False
    if prims and chunks is not None:
        inside = _focus(prims, chunks)
        if inside:
            prims, cap, focused = inside, FOCUS_MAX_SCALE * k, True
    if prims:
        x0, y0, x1, y1 = _bounds(prims) if focused else _fit_box(prims)
        bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        m = THUMB_MARGIN * k
        scale = min(cap, (width - 2 * m) / bw, (height - 2 * m) / bh)
        ox, oy = (width - bw * scale) / 2, (height - bh * scale) / 2

        def px(x: float, y: float) -> Point:
            return ox + (x - x0) * scale, oy + (y - y0) * scale

        shown = [p for p in prims if _touches(p, px, width, height)]
        _paint(ImageDraw.Draw(img), shown, px, scale, _thumb_style(k))
    return _png(img)
