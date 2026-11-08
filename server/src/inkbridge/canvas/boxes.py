"""Axis-aligned boxes over Excalidraw elements (INK-141)."""

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


def box(elements: list[dict]) -> Box | None:
    """Union bbox over x, y, width, height; None for an empty list."""
    if not elements:
        return None
    return (
        min(e["x"] for e in elements),
        min(e["y"] for e in elements),
        max(e["x"] + e.get("width", 0) for e in elements),
        max(e["y"] + e.get("height", 0) for e in elements),
    )


def intersects(a: Box | None, b: Box | None) -> bool:
    """Boxes that overlap or touch."""
    if a is None or b is None:
        return False
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
