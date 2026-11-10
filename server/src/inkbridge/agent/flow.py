"""Answer-in-place helpers (INK-201, decision 0116). Pure: no I/O."""

import random

FLOW_ARROW = "flow-arrow"


def answer_lead(text: str) -> str:
    return text if text.lstrip()[:7].lower() == "answer:" else f"Answer: {text}"


def arrow_for(prefix: str, anchor: dict, spot: dict, size: tuple[float, float]) -> dict | None:
    """Short arrow from the anchor's bottom (draft below) or right edge (draft right) to the draft."""
    w, h = size
    ax, ay, aw, ah = anchor["x"], anchor["y"], anchor["width"], anchor["height"]
    if spot["y"] >= ay + ah and spot["x"] < ax + aw:  # below
        x0, y0 = spot["x"] + min(aw, w) / 2, ay + ah
        x1, y1 = x0, spot["y"]
    elif spot["x"] >= ax + aw and spot["y"] < ay + ah:  # right
        y0 = min(max(ay + ah / 2, spot["y"]), spot["y"] + h)
        x0, x1, y1 = ax + aw, spot["x"], y0
    else:
        return None
    if abs(x1 - x0) + abs(y1 - y0) < 8:
        return None
    return {
        "id": f"{prefix}{FLOW_ARROW}",
        "type": "arrow",
        "x": x0,
        "y": y0,
        "width": abs(x1 - x0),
        "height": abs(y1 - y0),
        "angle": 0,
        "points": [[0, 0], [x1 - x0, y1 - y0]],
        "lastCommittedPoint": None,
        "startBinding": None,
        "endBinding": None,
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "elbowed": False,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "dashed",
        "roughness": 1,
        "opacity": 100,
        "roundness": None,
        "groupIds": [],
        "frameId": None,
        "boundElements": None,
        "link": None,
        "locked": False,
        "isDeleted": False,
        "updated": 0,
        "index": None,
        "seed": random.randrange(1, 2**31),
        "version": 1,
        "versionNonce": random.randrange(1, 2**31),
    }
