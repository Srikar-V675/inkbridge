"""Rule detectors that propose offers with no model call (INK-132, decision 0091).

Pure rules over the stored chunks; the caller (`run`, below) turns candidates into offers.
"""

import re
import sqlite3
from dataclasses import dataclass

from inkbridge import db

SCORE = {
    "question": 0.9,
    "stale_note": 0.8,
    "sketch": 0.6,
    "dangling_arrow": 0.5,
    "open_equation": 0.5,
    "related": 0.4,
    "to_note": 0.4,
}
TO_NOTE_MIN_CHUNKS = 8  # hypothesis, tune on logs
_QUESTION = re.compile(r"^\s*(why|how|what|should)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    kind: str
    anchor: str
    score: float
    payload: dict
    reason: str  # at most 8 words


def _cand(kind: str, anchor: str, payload: dict, reason: str) -> Candidate:
    return Candidate(kind, anchor, SCORE[kind], payload, reason)


def _question(c: dict) -> Candidate | None:
    text = (c["text"] or "").strip()
    if text and (_QUESTION.match(text) or text.endswith("?")):
        payload = {"action": "answer", "prepare": True, "key": c["text_hash"]}
        return _cand("question", c["id"], payload, "Looks like a question")


def _open_equation(c: dict) -> Candidate | None:
    for t in (c["text"], c["latex"]):
        if t and t.strip().endswith("="):
            return _cand(
                "open_equation",
                c["id"],
                {"action": "answer", "key": c["text_hash"]},
                "Equation left open",
            )


def _dangling(c: dict) -> Candidate | None:
    # chunker v2 makes a connector with a free end a chunk of its own
    if c["kind"] == "connector":
        payload = {"action": "ask_user", "key": c["content_hash"]}
        return _cand("dangling_arrow", c["id"], payload, "Arrow leads nowhere")


def _stale_note(chunks: list[dict], watches: list[dict]) -> list[Candidate]:
    by_id = {c["id"]: c for c in chunks}
    out, seen = [], set()
    for w in watches:
        c = by_id.get(w["chunk_id"])
        if c is None or c["text_hash"] is None or c["text_hash"] == w["reading_hash"]:
            continue
        if (w["note_id"], c["id"]) in seen:
            continue
        seen.add((w["note_id"], c["id"]))
        payload = {"action": "note", "note": w["note_id"], "key": c["text_hash"]}
        out.append(_cand("stale_note", c["id"], payload, "Note is out of date"))
    return out


def _to_note(chunks: list[dict], watches: list[dict]) -> list[Candidate]:
    if watches or len(chunks) < TO_NOTE_MIN_CHUNKS:
        return []
    # list_regions orders by updated_at DESC, so the first is the most recent
    return [
        _cand(
            "to_note", chunks[0]["id"], {"action": "note", "key": "canvas"}, "Turn this into a note"
        )
    ]


def scan(conn: sqlite3.Connection, document_id: str) -> list[Candidate]:
    all_chunks = db.list_regions(conn, document_id, chunks=True, status="active", limit=500)
    chunks = [c for c in all_chunks if c["source"] != "agent"]  # an agent's answer never triggers
    watches = db.list_watches(conn, document_id)
    out: list[Candidate] = []
    for c in chunks:
        out += [x for x in (_question(c), _open_equation(c), _dangling(c)) if x]
    out += _stale_note(chunks, watches)
    out += _to_note(chunks, watches)
    return sorted(out, key=lambda c: -c.score)
