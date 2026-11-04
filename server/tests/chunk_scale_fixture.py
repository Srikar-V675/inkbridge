"""Deterministic mixed-zoom canvas for INK-081: 1x handwriting and 10x handwriting on one page."""

from typing import Any


def _stroke(eid: str, x: float, y: float, w: float, h: float) -> dict[str, Any]:
    return {
        "id": eid, "type": "freedraw", "x": x, "y": y, "width": w, "height": h, "angle": 0,
        "isDeleted": False, "points": [[0, 0], [w, h]], "pressures": [0.5, 0.5],
    }  # fmt: skip


def mixed_zoom_canvas() -> list[dict[str, Any]]:
    """160 strokes at 1x (2 paragraphs, 8 lines of 10) and 160 at 10x, 6000 px to the right."""
    out = []
    for zoom, x0, line_pitch, para_pitch in ((1, 0, 30, 400), (10, 6000, 300, 4000)):
        for p in range(2):
            for line in range(8):
                for s in range(10):
                    h = 20 * zoom if zoom == 1 else 200 + (s % 5) * 30
                    out.append(
                        _stroke(
                            f"z{zoom}p{p}l{line}s{s}",
                            x0 + s * 15 * zoom,
                            p * para_pitch + line * line_pitch,
                            12 * zoom,
                            h,
                        )
                    )
    for i in range(3):
        out.append({**_stroke(f"rect{i}", 6000 + i * 400, 9000, 200, 600), "type": "rectangle"})
    return out
