"""Offers from the latest ink (INK-202, decision 0117).

After a quiet moment the strokes written since the last look are cropped on their own and sent to
Haiku with an intent prompt. A question or an open equation becomes an offer candidate that carries
the fresh text, so the offer does not wait for the chunk to be read. Drafts and agent ink never
reach the crop. If the scene changes during the call the result is dropped and the watermark stays,
so the next look covers the union. The reader is injectable; with no reader and no
INKBRIDGE_RECOGNIZER=claude the feature is off and the chunk detectors work as before.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable

from inkbridge import db
from inkbridge.agent.detectors import SCORE, Candidate
from inkbridge.canvas import raster
from inkbridge.db import elements as elements_db
from inkbridge.db import offers as offers_db
from inkbridge.db import supersede

log = logging.getLogger("inkbridge.offers.latest")

PROMPT = (
    "Transcribe the handwriting in this image. Reply with JSON only: "
    '{"text": "...", "intent": "question|equation|arrow_leads_nowhere|none"}. '
    'intent "question" is a complete question (a lone "?" counts). '
    'intent "equation" is an expression ending in "=" with no answer. '
    'Use "none" for anything else, including unfinished words.'
)
INTENTS = ("question", "equation", "arrow_leads_nowhere", "none")
KIND = {"question": "question", "equation": "open_equation"}
REASON = {"question": "Looks like a question", "equation": "Equation left open"}
PAD_FRACTION = 0.4  # hypothesis (decision 0117)
PAD_MAX = 300

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


def _box(ink: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(e.get("x", 0) for e in ink)
    y0 = min(e.get("y", 0) for e in ink)
    x1 = max(e.get("x", 0) + e.get("width", 0) for e in ink)
    y1 = max(e.get("y", 0) + e.get("height", 0) for e in ink)
    return x0, y0, x1, y1


def _pad(ink: list[dict]) -> int:
    x0, y0, x1, y1 = _box(ink)
    return min(PAD_MAX, max(raster.CROP_PAD, int(PAD_FRACTION * max(x1 - x0, y1 - y0))))


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
    chunks = supersede.active_chunks(conn, doc)
    if not chunks:
        return None
    ids = {e["id"] for e in ink if "id" in e}
    best = max(chunks, key=lambda c: len(ids & set(c["element_ids"])))
    if ids & set(best["element_ids"]):
        return best["id"]
    x0, y0, x1, y1 = _box(ink)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def dist(c: dict) -> float:
        b = c["bounds"]
        dx = max(b["x"] - cx, 0, cx - (b["x"] + b["width"]))
        dy = max(b["y"] - cy, 0, cy - (b["y"] + b["height"]))
        return dx * dx + dy * dy

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
    ink = _new_ink(conn, document_id, mark)
    if not ink:
        _mark[document_id] = head
        return []
    png = raster.render_crop(ink, pad=_pad(ink))
    if png is None:
        _mark[document_id] = head
        return []
    t0 = time.monotonic()
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
