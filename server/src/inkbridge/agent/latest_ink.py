"""Offers from the latest ink (INK-202, decision 0117).

After a quiet moment the strokes written since the last look are cropped on their own and sent to
Haiku with an intent prompt. A question or an open equation becomes an offer candidate that carries
the fresh text, so the offer does not wait for the chunk to be read. Drafts and agent ink never
reach the crop. If the scene changes during the call the result is dropped and the watermark stays,
so the next look covers the union. The reader is injectable; with no reader and no
INKBRIDGE_RECOGNIZER=claude the feature is off and the chunk detectors work as before.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import sqlite3
import time
from collections.abc import Callable

from PIL import Image

from inkbridge import db
from inkbridge.agent.detectors import SCORE, Candidate
from inkbridge.canvas import raster
from inkbridge.db import elements as elements_db
from inkbridge.db import offers as offers_db
from inkbridge.db import supersede

log = logging.getLogger("inkbridge.offers.latest")

PROMPT = (
    "Transcribe the handwriting in this image; give only the text of the writing, nothing else. "
    'Reply with JSON only: {"text": "...", "intent": "question|equation|arrow_leads_nowhere|none"}. '
    'intent "equation" is an expression ending in "=" with no answer written after it '
    '("2+2=" is an equation). '
    'intent "question" is a complete question in words ("What is X?"; a lone "?" counts). '
    'Use "none" for anything else, including unfinished words.'
)
INTENTS = ("question", "equation", "arrow_leads_nowhere", "none")
KIND = {"question": "question", "equation": "open_equation"}
REASON = {"question": "Looks like a question", "equation": "Equation left open"}
PAD_FRACTION = 0.4  # hypothesis (decision 0117)
PAD_MAX = 300
SLANT_MIN, SLANT_MAX = 8.0, 60.0  # degrees; hypothesis (decision 0117)
ELONGATED = 2.0  # principal axis at least this many times the minor axis

MAX_STROKES = 25  # hypothesis (decision 0119)
GAP_FACTOR = 2.0  # boxes within this many median stroke sizes join the cluster
WINDOW_MS = 10_000  # strokes updated within this of the newest
MIN_GAP_S, MAX_PER_MIN, MAX_PER_HOUR = 6.0, 8, 60
MAX_TEXT = 200

clock: Callable[[], float] = time.monotonic
_calls: dict[str, list[float]] = {}  # document -> monotonic times of recent reader calls
reader: Callable[[bytes], str] | None = None
stats = {"calls": 0, "dropped": 0, "errors": 0, "offered": 0}
_mark: dict[str, int] = {}  # document -> scene seq already looked at


def _reader() -> Callable[[bytes], str] | None:
    if reader is not None:
        return reader
    if os.environ.get("INKBRIDGE_RECOGNIZER", "").strip().lower() == "claude":
        from inkbridge.recognizer.claude import default_recognizer

        return lambda png: default_recognizer().read_ink(png, PROMPT)
    return None


def enabled() -> bool:
    return _reader() is not None


def _usable(e: dict) -> bool:
    custom = e.get("customData") if isinstance(e.get("customData"), dict) else {}
    return (
        e.get("type") == "freedraw"
        and not e.get("isDeleted")
        and not custom.get("draft")
        and custom.get("author") != "agent"
    )


def _new_ink(conn: sqlite3.Connection, doc: str, mark: int) -> list[dict]:
    out = []
    for r in elements_db.read_rows(conn, doc, live_only=True, since=mark):
        try:
            e = json.loads(r["json"])
        except ValueError:
            continue
        if isinstance(e, dict) and _usable(e):
            out.append(e)
    return out


def _side(e: dict) -> float:
    return max(abs(e.get("width", 0) or 0), abs(e.get("height", 0) or 0))


def newest_cluster(ink: list[dict]) -> list[dict]:
    """The strokes written last and close together: start from the newest stroke and grow while a
    stroke is within GAP_FACTOR median stroke sizes of the cluster and written within WINDOW_MS of
    the newest. At most MAX_STROKES, newest first."""
    if not ink:
        return []
    order = sorted(ink, key=lambda e: -(e.get("updated") or 0))
    sides = sorted(_side(e) for e in ink)
    gap = GAP_FACTOR * max(sides[len(sides) // 2], 10.0)
    newest = order[0].get("updated") or 0
    cluster = [order[0]]
    box = list(_box(cluster))
    rest = [e for e in order[1:] if newest - (e.get("updated") or 0) <= WINDOW_MS]
    grew = True
    while grew and len(cluster) < MAX_STROKES:
        grew = False
        for e in list(rest):
            ex0, ey0, ex1, ey1 = _box([e])
            if (
                ex0 - box[2] <= gap
                and box[0] - ex1 <= gap
                and ey0 - box[3] <= gap
                and box[1] - ey1 <= gap
            ):
                cluster.append(e)
                rest.remove(e)
                box = list(_box(cluster))
                grew = True
                if len(cluster) >= MAX_STROKES:
                    break
    return cluster


def _allowed(document_id: str) -> str:
    """'' when a call may go now, else why not: 'gap', 'minute' or 'hour'."""
    now = clock()
    calls = [t for t in _calls.get(document_id, ()) if now - t < 3600]
    _calls[document_id] = calls
    if len(calls) >= MAX_PER_HOUR:
        return "hour"
    if calls and now - calls[-1] < MIN_GAP_S:
        return "gap"
    if sum(1 for t in calls if now - t < 60) >= MAX_PER_MIN:
        return "minute"
    return ""


def _box(ink: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(e.get("x", 0) for e in ink)
    y0 = min(e.get("y", 0) for e in ink)
    x1 = max(e.get("x", 0) + e.get("width", 0) for e in ink)
    y1 = max(e.get("y", 0) + e.get("height", 0) for e in ink)
    return x0, y0, x1, y1


def _pad(ink: list[dict]) -> int:
    x0, y0, x1, y1 = _box(ink)
    return min(PAD_MAX, max(raster.CROP_PAD, int(PAD_FRACTION * max(x1 - x0, y1 - y0))))


def writing_angle(ink: list[dict]) -> float:
    """Dominant slant in degrees (positive = rising to the right) of elongated ink, else 0.0.

    Principal axis of all stroke points; only an elongated cluster whose angle is between
    SLANT_MIN and SLANT_MAX counts, so a horizontal line, a blob or a steep scribble gives 0."""
    pts = []
    for e in ink:
        for p in e.get("points") or ():
            try:
                pts.append((e.get("x", 0) + p[0], e.get("y", 0) + p[1]))
            except (TypeError, IndexError):
                continue
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    half = math.sqrt(((sxx - syy) / 2) ** 2 + sxy**2)
    major, minor = (sxx + syy) / 2 + half, (sxx + syy) / 2 - half
    if major <= 0 or (minor > 1e-9 and math.sqrt(major / minor) < ELONGATED):
        return 0.0
    return _axis(sxx, syy, sxy)


def _axis(sxx: float, syy: float, sxy: float) -> float:
    a = math.degrees(0.5 * math.atan2(-2 * sxy, sxx - syy))  # y is down on screen: flip
    return a if SLANT_MIN <= abs(a) <= SLANT_MAX else 0.0


def _level(png: bytes, angle: float) -> bytes:
    """Rotate the crop so the writing runs horizontally (white fill)."""
    if not angle:
        return png
    img = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    img.rotate(-angle, expand=True, fillcolor=(255, 255, 255)).save(out, "PNG")
    return out.getvalue()


def _parse(raw: str) -> tuple[str, str]:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        data = json.loads(s)
    except ValueError:
        return "", "none"
    if not isinstance(data, dict):
        return "", "none"
    text, intent = data.get("text"), data.get("intent")
    if not isinstance(text, str) or intent not in INTENTS:
        return "", "none"
    return text, intent


def _anchor(conn: sqlite3.Connection, doc: str, ink: list[dict]) -> str | None:
    """The smallest active chunk whose box holds the cluster's centre, else the nearest."""
    chunks = supersede.active_chunks(conn, doc)
    if not chunks:
        return None
    x0, y0, x1, y1 = _box(ink)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def dist(c: dict) -> float:
        b = c["bounds"]
        dx = max(b["x"] - cx, 0, cx - (b["x"] + b["width"]))
        dy = max(b["y"] - cy, 0, cy - (b["y"] + b["height"]))
        return dx * dx + dy * dy

    inside = [c for c in chunks if dist(c) == 0]
    if inside:
        return min(inside, key=lambda c: c["bounds"]["width"] * c["bounds"]["height"])["id"]
    return min(chunks, key=dist)["id"]


def _key(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def pending(conn: sqlite3.Connection, document_id: str) -> bool:
    """Ink newer than the watermark exists."""
    try:
        head = db.scene_version(conn, document_id)
    except db.DocumentNotFound:
        return False
    mark = _mark.get(document_id, head - 1)
    return bool(_new_ink(conn, document_id, mark))


def _log(doc: str, t0: float, ink: list[dict], intent: str, text: str, outcome: str) -> None:
    log.info(
        "doc=%s ms=%d strokes=%d intent=%s text_len=%d outcome=%s calls=%d",
        doc,
        (time.monotonic() - t0) * 1000,
        len(ink),
        intent,
        len(text),
        outcome,
        stats["calls"],
    )


def poll(conn: sqlite3.Connection, document_id: str) -> list[Candidate]:
    fn = _reader()
    if fn is None or offers_db.open_offers(conn, document_id):
        return []
    head = db.scene_version(conn, document_id)
    mark = _mark.setdefault(document_id, head - 1)
    batch = _new_ink(conn, document_id, mark)
    if not batch:
        _mark[document_id] = head
        return []
    why = _allowed(document_id)
    if why:
        if why == "hour":
            _mark[document_id] = head  # give this batch up; do not retry for ever
        log.info("doc=%s outcome=capped by=%s strokes=%d", document_id, why, len(batch))
        return []
    ink = newest_cluster(batch)
    png = raster.render_crop(ink, pad=_pad(ink))
    if png is None:
        _mark[document_id] = head
        return []
    png = _level(png, writing_angle(ink))
    t0 = time.monotonic()
    _calls.setdefault(document_id, []).append(clock())
    stats["calls"] += 1
    try:
        raw = fn(png)
    except Exception as e:  # noqa: BLE001 - any reader failure falls back to the chunk detectors
        stats["errors"] += 1
        _mark[document_id] = head
        _log(document_id, t0, ink, type(e).__name__, "", "error")
        return []
    if db.scene_version(conn, document_id) != head:
        stats["dropped"] += 1
        _log(document_id, t0, ink, "-", "", "dropped")
        return []
    _mark[document_id] = head
    text, intent = _parse(raw)
    if intent in KIND and len(text) > MAX_TEXT:
        _log(document_id, t0, ink, intent, text, "too_long")  # the crop was wrong
        return []
    if intent not in KIND or not text.strip():
        _log(document_id, t0, ink, intent, text, "none")
        return []
    anchor = _anchor(conn, document_id, ink)
    if anchor is None:
        _log(document_id, t0, ink, intent, text, "none")
        return []
    kind = KIND[intent]
    payload: dict = {"action": "answer", "key": _key(text), "text": text, "src": "latest"}
    if kind == "question":
        payload["prepare"] = True
    stats["offered"] += 1
    _log(document_id, t0, ink, intent, text, "offered")
    return [Candidate(kind, anchor, SCORE[kind], payload, REASON[intent])]
