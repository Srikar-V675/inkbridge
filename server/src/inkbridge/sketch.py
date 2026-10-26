"""Pass 1 of the two-pass sketch reading (INK-058). Pure: no I/O, no model.

From the elements of a hand-drawn diagram, guess the nodes (closed shapes) and the arrows (open
strokes that touch two nodes) so an agent can be shown numbered markers (N1, A1, ...) and asked
for Mermaid that cites them, instead of guessing the whole structure from pixels in one shot.

Heuristics, each giving a confidence in [0, 1]:
- A node is a native rectangle, ellipse or diamond (1.0), or a freedraw stroke whose two ends
  nearly meet and whose path is long for its box (a loop). Strokes and text inside a node are
  its label, never arrows.
- An arrow is a native arrow or line, or an open freedraw stroke, whose two ends are each near a
  different node. Its head is: a native arrowhead; a small separate stroke (the V) next to one
  end; or a hook, where the stroke turns back at its far end, so the end farthest from the shaft's
  start is the tip. Arrows always point from -> to; without a head the drawing order is kept and
  the confidence is lower.
- Strokes that touch fewer than two nodes are listed as `unattached`: the agent must say whether
  they are arrows with a missing source or target.
Rotation (`angle`) is ignored, as in `regions.bbox_of`.
"""

import itertools
import math
from typing import Any

from inkbridge.regions import bbox_of

SHAPES = ("rectangle", "ellipse", "diamond")
MIN_NODE_SIZE = 20.0  # px diagonal: smaller loops are letters (o, a), not boxes
CLOSURE = 0.25  # ends of a loop are within this fraction of its box diagonal
LOOP_LENGTH = 1.8  # a loop's path is at least this many box diagonals long
HEAD_SIZE = 0.4  # a separate head stroke is at most this fraction of the shaft's length
HOOK = 0.05  # path left after the tip, as a fraction of the stroke, that counts as a hook

Point = tuple[float, float]
Box = dict[str, float]


def _points(e: dict[str, Any]) -> list[Point]:
    x, y = e.get("x", 0), e.get("y", 0)
    return [(x + p[0], y + p[1]) for p in e.get("points") or []]


def _length(pts: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in itertools.pairwise(pts))


def _diag(box: Box) -> float:
    return math.hypot(box["width"], box["height"])


def _centre(box: Box) -> Point:
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _inside(p: Point, box: Box) -> bool:
    return (
        box["x"] <= p[0] <= box["x"] + box["width"] and box["y"] <= p[1] <= box["y"] + box["height"]
    )


def _distance(p: Point, box: Box) -> float:
    """0 inside the box, else the distance to its edge."""
    dx = max(box["x"] - p[0], 0, p[0] - box["x"] - box["width"])
    dy = max(box["y"] - p[1], 0, p[1] - box["y"] - box["height"])
    return math.hypot(dx, dy)


def _loop_confidence(e: dict[str, Any]) -> float:
    """> 0 if a freedraw stroke is a closed loop big enough to be a node."""
    pts = _points(e)
    if e.get("type") != "freedraw" or len(pts) < 4:
        return 0.0
    box = bbox_of([e])
    d = _diag(box)
    if d < MIN_NODE_SIZE:
        return 0.0
    gap = math.dist(pts[0], pts[-1])
    if gap > CLOSURE * d or _length(pts) < LOOP_LENGTH * d:
        return 0.0
    return round(1.0 - 0.5 * gap / (CLOSURE * d), 3)


def _tip(pts: list[Point]) -> tuple[int, bool]:
    """Index of the point farthest from the start, and whether the stroke hooks back after it."""
    far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
    total = _length(pts) or 1.0
    return far, _length(pts[far:]) > HOOK * total


def _finite(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def usable(e: Any) -> bool:
    """Skip malformed elements instead of failing the whole read (the scene is stored as sent)."""
    if not isinstance(e, dict) or not isinstance(e.get("id"), str):
        return False
    if not all(_finite(e.get(k, 0)) for k in ("x", "y", "width", "height")):
        return False
    if e.get("type") in SHAPES and not (e.get("width", 0) > 0 and e.get("height", 0) > 0):
        return False
    if "text" in e and not isinstance(e["text"], str | None):
        return False
    pts = e.get("points")
    return pts is None or (
        isinstance(pts, list)
        and all(
            isinstance(p, list | tuple) and len(p) >= 2 and _finite(p[0]) and _finite(p[1])
            for p in pts
        )
    )


def read_sketch(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Nodes, arrows and unattached strokes of a sketch, with confidences and element ids."""
    live = [e for e in elements if not e.get("isDeleted") and usable(e)]
    nodes: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for e in live:
        if e.get("type") in SHAPES:
            nodes.append({"box": bbox_of([e]), "element_ids": [e["id"]], "confidence": 1.0})
        elif (c := _loop_confidence(e)) > 0:
            nodes.append({"box": bbox_of([e]), "element_ids": [e["id"]], "confidence": c})
        else:
            rest.append(e)

    # Reading order: top to bottom, then left to right (rows of about a node's height).
    row = max(1.0, min((n["box"]["height"] for n in nodes), default=1.0))
    nodes.sort(key=lambda n: (round(n["box"]["y"] / row), n["box"]["x"]))
    for i, n in enumerate(nodes, 1):
        n["id"] = f"N{i}"
        n["label_element_ids"] = []
        n["label_text"] = None

    # Labels: anything whose centre lies inside a node (bound text of a native shape, or ink).
    candidates = []
    for e in rest:
        box = bbox_of([e])
        home = next(
            (
                n
                for n in sorted(nodes, key=lambda n: _diag(n["box"]))
                if _inside(_centre(box), n["box"]) and _diag(box) < _diag(n["box"])
            ),
            None,
        )
        if home is not None and e.get("type") not in ("arrow", "line"):
            home["label_element_ids"].append(e["id"])
            if e.get("type") == "text" and e.get("text"):
                home["label_text"] = " ".join(filter(None, [home["label_text"], e["text"]]))
        elif e.get("type") == "text":
            continue  # free text (an edge label, a title) is shown on the image, not guessed
        elif _points(e):
            candidates.append(e)

    sizes = sorted(_diag(n["box"]) for n in nodes)
    tol = max(15.0, 0.15 * sizes[len(sizes) // 2]) if sizes else 15.0
    arrows: list[dict[str, Any]] = []

    def nearest(p: Point) -> tuple[dict | None, float]:
        best = min(nodes, key=lambda n: _distance(p, n["box"]), default=None)
        return best, (_distance(p, best["box"]) if best else math.inf)

    # First classify every stroke: one whose two ends touch two different nodes is a shaft.
    # Only the others can be arrowheads, so a short arrow is never taken as a longer one's head.
    shafts: list[dict[str, Any]] = []
    pool: list[dict[str, Any]] = []
    for e in candidates:
        pts = _points(e)
        if len(pts) < 2:
            pool.append(e)
            continue
        start, end, head, evidence = pts[0], pts[-1], None, 0.0
        if e.get("type") in ("arrow", "line"):
            if e.get("endArrowhead") and e.get("startArrowhead"):
                head, evidence = "both", 1.0
            elif e.get("endArrowhead"):
                head, evidence = "end", 1.0
            elif e.get("startArrowhead"):
                head, evidence = "start", 1.0
        else:
            far, hooked = _tip(pts)
            if hooked:
                end, head, evidence = pts[far], "end", 0.8
        a, da = nearest(start)
        b, db = nearest(end)
        # A native arrow bound to a shape names its node exactly.
        for side in ("startBinding", "endBinding"):
            bound = (e.get(side) or {}).get("elementId")
            node = next((n for n in nodes if bound in n["element_ids"]), None)
            if node is not None:
                if side == "startBinding":
                    a, da = node, 0.0
                else:
                    b, db = node, 0.0
        if a is None or b is None or a is b or da > tol or db > tol:
            pool.append(e)
            continue
        shafts.append(
            {
                "e": e,
                "pts": pts,
                "start": start,
                "end": end,
                "head": head,
                "evidence": evidence,
                "a": a,
                "da": da,
                "b": b,
                "db": db,
            }
        )

    used: set[str] = set()
    for sh in sorted(shafts, key=lambda sh: -_length(sh["pts"])):
        e, start, end, head, evidence = sh["e"], sh["start"], sh["end"], sh["head"], sh["evidence"]
        a, da, b, db = sh["a"], sh["da"], sh["b"], sh["db"]
        ids = [e["id"]]
        if head is None:
            # A separate small stroke near one end is the arrowhead.
            shaft = _length(sh["pts"])
            for h in pool:
                if h["id"] in used or not _points(h):
                    continue
                hb = bbox_of([h])
                if _diag(hb) > HEAD_SIZE * shaft:
                    continue
                d_end, d_start = _distance(end, hb), _distance(start, hb)
                if min(d_end, d_start) <= tol / 2:
                    head = "end" if d_end <= d_start else "start"
                    evidence = 0.9
                    ids.append(h["id"])
                    used.add(h["id"])
                    break
        if head == "start":
            a, b, da, db, start, end = b, a, db, da, end, start
            head = "end"
        # Ends within a third of the tolerance count as touching (pens and arrows leave a gap).
        slack = tol / 3
        attach = 1.0 - 0.5 * (max(0.0, da - slack) + max(0.0, db - slack)) / (2 * tol)
        confidence = (evidence if head else 0.5) * attach
        arrows.append(
            {
                "from": a["id"],
                "to": b["id"],
                "head": head,  # "end" (points at `to`), "both", or None (direction guessed)
                "tip": {"x": end[0], "y": end[1]},
                "tail": {"x": start[0], "y": start[1]},
                "element_ids": ids,
                "confidence": round(confidence, 3),
            }
        )
    unattached = [e["id"] for e in pool if e["id"] not in used]
    arrows.sort(key=lambda r: (int(r["from"][1:]), int(r["to"][1:])))
    for i, r in enumerate(arrows, 1):
        r["id"] = f"A{i}"
    return {
        "nodes": [
            {
                "id": n["id"],
                "box": n["box"],
                "element_ids": n["element_ids"],
                "label_element_ids": n["label_element_ids"],
                "label_text": n["label_text"],
                "confidence": n["confidence"],
            }
            for n in nodes
        ],
        "arrows": [{"id": r.pop("id"), **r} for r in arrows],
        "unattached": sorted(set(unattached)),
    }
