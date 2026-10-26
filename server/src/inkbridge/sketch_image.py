"""Marker image for the two-pass sketch reading (INK-058). Pure: elements in, PNG bytes out.

The server renders the ink itself instead of drawing on the browser's crop: the crop's padding
and scale are the browser's, while here every marker lands exactly on the geometry pass 1 used.
Node markers (red, N1...) sit on node centres, arrow markers (blue, A1...) on arrow tips, and
unattached strokes get grey markers (U1..., in `unattached` order) at their middle point.
"""

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from inkbridge.regions import bbox_of

PAD = 30
MAX_WIDTH = 1024
MAX_SCALE = 2.0
RADIUS = 12
NODE_COLOUR = (220, 38, 38)
ARROW_COLOUR = (37, 99, 235)
UNATTACHED_COLOUR = (115, 115, 115)
INK = (60, 60, 60)


def render_markers(
    elements: list[dict[str, Any]], structure: dict[str, Any], max_width: int = MAX_WIDTH
) -> tuple[bytes, list[dict[str, Any]]]:
    """PNG of the ink with numbered markers, and each marker's pixel position."""
    live = [e for e in elements if not e.get("isDeleted")]
    if not live:
        raise ValueError("no live elements to draw")
    box = bbox_of(live)
    scale = min(MAX_SCALE, (max_width - 2 * PAD) / max(box["width"], 1.0))
    width = round(box["width"] * scale) + 2 * PAD
    height = round(box["height"] * scale) + 2 * PAD

    def px(x: float, y: float) -> tuple[float, float]:
        return (PAD + (x - box["x"]) * scale, PAD + (y - box["y"]) * scale)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    for e in live:
        x, y = e.get("x", 0), e.get("y", 0)
        if e.get("points"):
            pts = [px(x + p[0], y + p[1]) for p in e["points"]]
            if len(pts) > 1:
                draw.line(pts, fill=INK, width=2, joint="curve")
        elif e.get("type") in ("rectangle", "diamond", "ellipse"):
            x0, y0 = px(x, y)
            x1, y1 = px(x + e.get("width", 0), y + e.get("height", 0))
            if e["type"] == "ellipse":
                draw.ellipse([x0, y0, x1, y1], outline=INK, width=2)
            elif e["type"] == "diamond":
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                draw.polygon([(mx, y0), (x1, my), (mx, y1), (x0, my)], outline=INK, width=2)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=INK, width=2)
        elif e.get("type") == "text" and e.get("text"):
            draw.text(px(x, y), str(e["text"])[:200], fill=INK, font=font)

    markers = []

    def badge(label: str, at: tuple[float, float], colour: tuple[int, int, int], **extra) -> None:
        cx, cy = at
        draw.ellipse([cx - RADIUS, cy - RADIUS, cx + RADIUS, cy + RADIUS], fill=colour)
        draw.text((cx, cy), label, fill="white", font=font, anchor="mm")
        markers.append({"id": label, "x": round(cx, 1), "y": round(cy, 1), **extra})

    for n in structure["nodes"]:
        b = n["box"]
        badge(n["id"], px(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2), NODE_COLOUR)
    for a in structure["arrows"]:
        badge(a["id"], px(a["tip"]["x"], a["tip"]["y"]), ARROW_COLOUR)
    by_id = {e["id"]: e for e in live}
    for i, eid in enumerate(structure.get("unattached", []), 1):
        e = by_id.get(eid)
        if e is None or not e.get("points"):
            continue
        mx, my = e["points"][len(e["points"]) // 2][:2]
        badge(
            f"U{i}", px(e.get("x", 0) + mx, e.get("y", 0) + my), UNATTACHED_COLOUR, element_id=eid
        )
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue(), markers
