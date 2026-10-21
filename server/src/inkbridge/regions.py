"""Pure region maths: bbox and stroke hash. No I/O, no SQLite."""

import hashlib
import json
from typing import Any

# Ink-defining fields only. Never add version, versionNonce, updated, seed or customData:
# they change on every render and would invalidate the recognition cache.
HASH_FIELDS = (
    "id",
    "type",
    "x",
    "y",
    "width",
    "height",
    "angle",
    "points",
    "pressures",
    "isDeleted",
)


def stroke_hash(elements: list[dict[str, Any]]) -> str:
    rows = [
        {**{k: el[k] for k in HASH_FIELDS if k in el}, "isDeleted": bool(el.get("isDeleted"))}
        for el in elements
    ]
    rows.sort(key=lambda r: str(r.get("id")))
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def bbox_of(elements: list[dict[str, Any]]) -> dict[str, float]:
    """Axis-aligned bounds of the ink (rotation ignored).

    Excalidraw keeps x,y at a stroke's first point and its points are relative to it, possibly
    negative, so strokes use their point extents; other elements use x/y/width/height.
    Deleted elements are skipped unless every element is deleted.
    """
    live = [e for e in elements if not e.get("isDeleted")] or elements
    xs: list[float] = []
    ys: list[float] = []
    for e in live:
        x, y = e.get("x", 0), e.get("y", 0)
        pts = e.get("points")
        if pts:
            xs += [x + min(p[0] for p in pts), x + max(p[0] for p in pts)]
            ys += [y + min(p[1] for p in pts), y + max(p[1] for p in pts)]
        else:
            xs += [x, x + e.get("width", 0)]
            ys += [y, y + e.get("height", 0)]
    return {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
