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
    """Axis-aligned bounds from x/y/width/height (rotation ignored).

    Deleted elements are skipped unless every element is deleted.
    """
    live = [e for e in elements if not e.get("isDeleted")] or elements
    xs, ys = [], []
    for e in live:
        x, y = e.get("x", 0), e.get("y", 0)
        w, h = e.get("width", 0), e.get("height", 0)
        xs += [x, x + w]
        ys += [y, y + h]
    return {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
