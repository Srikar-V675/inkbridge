"""Stroke kinds (INK-121). Pure: no I/O, no model, not wired into the chunker yet (INK-122).

Labels every live stroke from its shape alone: writing, container (a closed loop with ink
inside), connector (a long straight or hooked stroke with a head, a hook or a shape at an end, or a
native arrow/line; a bare long stroke is writing, INK-195), head (the small
stroke that makes an arrow's tip), underline (a flat stroke under writing) or scribble (a tight
zigzag). Text, native shapes and anything else are never keys. Rotation is ignored.

T is the scale of the writing: the median extent of the strokes after dropping those a first
median already calls long. Every size test is a multiple of T, so the rules hold at any zoom.
Thresholds are start values; E5 on real pages tunes them.
"""

import itertools
import math
from dataclasses import dataclass
from typing import Any

from inkbridge.canvas.hashes import bbox_of
from inkbridge.canvas.sketch import Box, Point, _length, _tip, usable

KINDS = ("writing", "container", "connector", "head", "underline", "scribble")

LONG = 1.5  # extent > LONG*T: container/connector (start value, tune on real pages)
HEAD_MAX = 0.6  # head: extent < HEAD_MAX*T (start value, tune on real pages)
HEAD_REACH = 0.75  # head: within this*T of a connector end (start value, tune on real pages)
HEAD_ORDER = 2  # head: at most this many strokes after its shaft (start value, tune on real pages)
CONTAINER_CLOSE = 0.25  # container: net < this * diag (start value, tune on real pages)
CONTAINER_LOOP = 1.8  # container: L >= this * diag (start value, tune on real pages)
STRAIGHT = 0.55  # connector: net / L above this (start value, tune on real pages)
FLAT = 0.15  # underline: h < FLAT * w (start value, tune on real pages)
UNDERLINE_MIN = 1.0  # underline, scribble: extent >= this*T (start value, tune on real pages)
UNDERLINE_REACH = 0.75  # writing at most this*T above it (start value, tune on real pages)
UNDERLINE_TOUCH = 0.5  # ... or overlapping it by at most this*T (start value, tune on real pages)
SCRIBBLE_REVERSALS = 6  # scribble: at least this many reversals (start value, tune on real pages)
SCRIBBLE_LOOP = 4.0  # ... and path length >= this*diag (start value, tune on real pages)
MIN_SCALE = 4.0  # floor for T in px (start value, tune on real pages)
HOOK_MAX = 0.4  # a hook's barb is at most this fraction of the path (the sketch HEAD_SIZE)
MIN_STEP = 0.02  # reversal counting ignores steps smaller than this * diag


@dataclass(frozen=True)
class StrokeKinds:
    kinds: dict[str, str]  # element id -> kind, for live freedraw strokes and native arrow/line
    head_of: dict[str, str]  # head id -> id of the connector it belongs to
    scale: float  # T, median extent of the writing (0.0 when there are no strokes)


@dataclass(frozen=True)
class _F:
    id: str
    pos: int  # draw-order rank among the classified strokes
    box: Box
    w: float
    h: float
    extent: float
    diag: float
    L: float
    net: float
    pts: list[Point]
    cx: float
    cy: float


def _order(indices: list[str | None]) -> list[int]:
    """Positions sorted into draw order: fractional index, list position when it is missing."""
    return sorted(range(len(indices)), key=lambda i: (indices[i] is None, indices[i] or "", i))


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _scale(extents: list[float]) -> float:
    if not extents:
        return 0.0
    t0 = _median(extents)  # pass 1: everything
    short = [x for x in extents if x <= LONG * t0]  # drop what pass 1 already calls long
    return max(MIN_SCALE, _median(short or extents))  # pass 2: the writing


def _features(
    elements: list[dict[str, Any]],
) -> tuple[list[_F], list[dict[str, Any]], list[Box], list[Box]]:
    """Live freedraw strokes in draw order, native arrows/lines, text boxes and shape boxes."""
    live = [e for e in elements if usable(e) and not _dead(e)]
    idx = [e.get("index") if isinstance(e.get("index"), str) else None for e in live]
    feats: list[_F] = []
    natives: list[dict[str, Any]] = []
    texts: list[Box] = []
    shapes: list[Box] = []
    for i in _order(idx):
        e = live[i]
        if e.get("type") in ("arrow", "line"):
            natives.append(e)
        elif e.get("type") in ("rectangle", "ellipse", "diamond", "frame"):
            shapes.append(bbox_of([e]))
        elif e.get("type") == "text":
            texts.append(bbox_of([e]))
        elif e.get("type") == "freedraw":
            box = bbox_of([e])
            pts = [(e.get("x", 0) + p[0], e.get("y", 0) + p[1]) for p in e.get("points") or []]
            w, h = box["width"], box["height"]
            feats.append(
                _F(
                    id=e["id"],
                    pos=len(feats),
                    box=box,
                    w=w,
                    h=h,
                    extent=max(w, h),
                    diag=math.hypot(w, h),
                    L=_length(pts),
                    net=math.dist(pts[0], pts[-1]) if pts else 0.0,
                    pts=pts,
                    cx=box["x"] + w / 2,
                    cy=box["y"] + h / 2,
                )
            )
    return feats, natives, texts, shapes


def _dead(e: dict[str, Any]) -> bool:
    cd = e.get("customData")
    return bool(e.get("isDeleted")) or (isinstance(cd, dict) and bool(cd.get("draft")))


def _inside_polygon(p: Point, pts: list[Point]) -> bool:
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in itertools.pairwise(pts + pts[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _reversals(pts: list[Point], diag: float) -> int:
    """Direction changes along the path: the larger count of dx and dy sign changes."""
    floor = MIN_STEP * diag
    best = 0
    for axis in (0, 1):
        last = 0
        count = 0
        for a, b in itertools.pairwise(pts):
            d = b[axis] - a[axis]
            if abs(d) < floor:
                continue
            sign = 1 if d > 0 else -1
            if last and sign != last:
                count += 1
            last = sign
        best = max(best, count)
    return best


def _holds_ink(f: _F, feats: list[_F]) -> bool:
    """True if a smaller stroke's centre lies inside the polygon of the closed stroke f."""
    b = f.box
    for o in feats:
        if o.id == f.id or o.extent >= f.extent:
            continue
        if not (b["x"] <= o.cx <= b["x"] + f.w and b["y"] <= o.cy <= b["y"] + f.h):
            continue
        if _inside_polygon((o.cx, o.cy), f.pts):
            return True
    return False


def _dist_point_box(p: Point, box: Box) -> float:
    """0 inside the box, else the distance to its edge."""
    dx = max(box["x"] - p[0], 0, p[0] - box["x"] - box["width"])
    dy = max(box["y"] - p[1], 0, p[1] - box["y"] - box["height"])
    return math.hypot(dx, dy)


def _flat(f: _F) -> bool:
    return f.h < FLAT * f.w


def _has_hook(f: _F) -> bool:
    """A straight shaft with a trailing barb of at most HOOK_MAX of the path.

    The part up to the tip must itself be straight, or the last loop of a cursive word reads
    as a barb.
    """
    if len(f.pts) < 3:
        return False
    far, hooked = _tip(f.pts)
    if not hooked or _length(f.pts[far:]) > HOOK_MAX * f.L:
        return False
    shaft = _length(f.pts[: far + 1])
    return shaft > 0 and math.dist(f.pts[0], f.pts[far]) / shaft > STRAIGHT


def _find_head(f: _F, feats: list[_F], head_of: dict[str, str], t: float) -> _F | None:
    """The first unclaimed small stroke just after f in draw order, at one of its ends."""
    ends = (f.pts[0], f.pts[-1])
    for h in feats[f.pos + 1 : f.pos + 1 + HEAD_ORDER]:
        if h.id in head_of or h.extent >= HEAD_MAX * t:
            continue
        if any(_dist_point_box(p, h.box) <= HEAD_REACH * t for p in ends):
            return h
    return None


def _column(x: float, t: float) -> int:
    return int(x // (2 * t))


def _writing_above(u: _F, columns: dict[int, list[Box]], t: float) -> bool:
    """Writing whose centre x is over the underline and whose bottom sits just above it."""
    top = u.box["y"]
    for col in range(_column(u.box["x"], t), _column(u.box["x"] + u.w, t) + 1):
        for b in columns.get(col, ()):
            cx = b["x"] + b["width"] / 2
            gap = top - (b["y"] + b["height"])
            if (
                u.box["x"] <= cx <= u.box["x"] + u.w
                and -UNDERLINE_TOUCH * t <= gap <= UNDERLINE_REACH * t
            ):
                return True
    return False


def analyse(elements: list[dict[str, Any]]) -> StrokeKinds:
    feats, natives, texts, shapes = _features(elements)
    kinds: dict[str, str] = {e["id"]: "connector" for e in natives}
    head_of: dict[str, str] = {}
    if not feats:
        return StrokeKinds(kinds=kinds, head_of=head_of, scale=0.0)
    scale = _scale([f.extent for f in feats])

    # Closed loops with ink inside, and tight zigzags.
    rest: list[_F] = []
    for f in feats:
        if (
            f.extent > LONG * scale
            and f.net < CONTAINER_CLOSE * f.diag
            and f.L >= CONTAINER_LOOP * f.diag
            and _holds_ink(f, feats)
        ):
            kinds[f.id] = "container"
        elif (
            f.extent >= UNDERLINE_MIN * scale
            and f.L >= SCRIBBLE_LOOP * f.diag
            and _reversals(f.pts, f.diag) >= SCRIBBLE_REVERSALS
        ):
            kinds[f.id] = "scribble"
        else:
            rest.append(f)

    # Shafts in draw order, so each head is claimed once. Heads are decided before underlines.
    shafts: list[_F] = []
    evidence: set[str] = set()
    for f in rest:
        if f.extent <= LONG * scale or f.L <= 0:
            continue
        hook = _has_hook(f)
        if not (f.net / f.L > STRAIGHT or hook):
            continue
        shafts.append(f)
        head = _find_head(f, feats, head_of, scale)
        if head is not None:
            head_of[head.id] = f.id
        if hook or head is not None:
            evidence.add(f.id)
    for hid in head_of:
        kinds[hid] = "head"

    # A bare straight stroke is evidence of nothing; one that ends on a shape or a container loop
    # is a link between two things (INK-195).
    anchors = shapes + [f.box for f in feats if kinds.get(f.id) == "container"]
    for f in shafts:
        if f.id not in evidence and any(
            _dist_point_box(p, a) <= HEAD_REACH * scale for p in (f.pts[0], f.pts[-1]) for a in anchors
        ):
            evidence.add(f.id)

    # Writing that an underline can sit under: small, not flat, not a head; native text too.
    columns: dict[int, list[Box]] = {}
    for f in rest:
        if f.extent <= LONG * scale and not _flat(f) and f.id not in head_of:
            columns.setdefault(_column(f.cx, scale), []).append(f.box)
    for b in texts:
        columns.setdefault(_column(b["x"] + b["width"] / 2, scale), []).append(b)

    for f in rest:
        if f.id in head_of:
            continue
        if f.id in evidence:
            kinds[f.id] = "connector"
        elif _flat(f) and f.extent >= UNDERLINE_MIN * scale and _writing_above(f, columns, scale):
            kinds[f.id] = "underline"
        else:
            kinds[f.id] = "writing"
    return StrokeKinds(kinds=kinds, head_of=head_of, scale=scale)


def classify(elements: list[dict[str, Any]]) -> dict[str, str]:
    return analyse(elements).kinds
