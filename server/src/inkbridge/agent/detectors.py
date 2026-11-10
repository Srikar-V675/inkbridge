"""Rule detectors that propose offers with no model call (INK-132, decision 0091).

Pure rules over the stored chunks; the caller (`run`, below) turns candidates into offers.
"""

import json
import re
import sqlite3
from dataclasses import dataclass

from inkbridge import db
from inkbridge.agent import markup
from inkbridge.canvas.sketch import read_sketch
from inkbridge.db import diagrams as diagrams_db
from inkbridge.db import offers as offers_db

SCORE = {
    "question": 0.9,
    "markup": 0.85,
    "stale_note": 0.8,
    "stale_diagram": 0.7,
    "sketch": 0.6,
    "dangling_arrow": 0.5,
    "open_equation": 0.5,
    "related": 0.4,
    "to_note": 0.4,
}
TO_NOTE_MIN_CHUNKS = 8  # hypotheses, tune on logs
RELATED_MIN_SCORE = 3.0  # -bm25
RELATED_CHUNKS = 20
SKETCH_CHUNKS = 30
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
    if watches or len(chunks) < TO_NOTE_MIN_CHUNKS:  # chunks are already tiny-free
        return []
    biggest = max(chunks, key=lambda c: len(c["element_ids"]))  # max keeps the first of equals
    return [_cand("to_note", biggest["id"], {"action": "note", "key": "canvas"}, "Turn this into a note")]


def _seen_key(kind: str, anchor: str, key) -> tuple:
    # to_note is one offer per canvas: the anchor may move, the offer must not repeat
    return (kind, None if kind == "to_note" else anchor, key)


MIN_ELEMENTS = 2


def _tiny(c: dict) -> bool:
    # a dot or a stray tick: never an anchor (INK-183); a connector chunk is one element by design
    return (
        c["kind"] != "connector"
        and len(c["element_ids"]) < MIN_ELEMENTS
        and len((c["text"] or "").strip()) < 2
    )


def scan(conn: sqlite3.Connection, document_id: str) -> list[Candidate]:
    all_chunks = db.list_regions(conn, document_id, chunks=True, status="active", limit=500)
    chunks = [c for c in all_chunks if c["source"] != "agent" and not _tiny(c)]  # an agent's answer never triggers
    watches = db.list_watches(conn, document_id)
    out: list[Candidate] = []
    for c in chunks:
        out += [x for x in (_question(c), _open_equation(c), _dangling(c)) if x]
    out += _stale_note(chunks, watches)
    out += _to_note(chunks, watches)
    out += _stale_diagram(conn, document_id, chunks)
    out += _sketch(conn, document_id, chunks)
    out += _related(conn, document_id, chunks)
    out += _markup(conn, document_id, all_chunks)
    return sorted(out, key=lambda c: -c.score)


def _stale_diagram(conn: sqlite3.Connection, document_id: str, chunks: list[dict]) -> list[Candidate]:
    # shortcut: a chunk replaced by a new id is skipped (no successor follow), see decision 0100
    by_id = {c["id"]: c for c in chunks}
    out = []
    for d in diagrams_db.list_accepted(conn, document_id):
        for snap in d["from_chunks"]:
            c = by_id.get(snap["chunk"])
            if c is None or snap["text_hash"] is None or c["text_hash"] in (None, snap["text_hash"]):
                continue
            payload = {"action": "diagram", "diagram": d["id"], "key": f"{d['id']}:{c['text_hash']}"}
            out.append(_cand("stale_diagram", c["id"], payload, "Diagram may be out of date"))
            break  # one offer per diagram
    return out


def _sketch(conn: sqlite3.Connection, document_id: str, chunks: list[dict]) -> list[Candidate]:
    # shortcut: re-reads up to 30 chunks per scan, cache by content_hash if the logs show cost
    links = db.list_links(conn, document_id)
    linked = {x for link in links for x in (link["from"], link["to"])}
    partners: dict[str, set[str]] = {}
    for link in links:
        partners.setdefault(link["from"], set()).add(link["to"])
        partners.setdefault(link["to"], set()).add(link["from"])
    pool = [
        c
        for c in chunks
        if c["kind"] != "connector" and (c["id"] in linked or len(c["element_ids"]) >= 3)
    ][:SKETCH_CHUNKS]
    claimed: set[str] = set()
    out = []
    by_id = {e["id"]: e for e in json.loads(db.get_scene(conn, document_id)[1])} if pool else {}
    for c in pool:
        if c["id"] in claimed:
            continue
        s = read_sketch(db.get_sketch_elements(conn, c["id"], by_id) or [])
        if len(s["nodes"]) >= 3 and len(s["arrows"]) >= 2:
            payload = {"action": "diagram", "key": c["content_hash"]}
            out.append(_cand("sketch", c["id"], payload, "Draw this cleanly"))
            claimed |= {c["id"], *partners.get(c["id"], ())}
    return out


def _fts_or(text: str) -> str | None:
    words = sorted({w.lower() for w in re.findall(r"\w{4,}", text)}, key=len, reverse=True)[:6]
    return " OR ".join(f'"{w}"' for w in words) or None


def _related(conn: sqlite3.Connection, document_id: str, chunks: list[dict]) -> list[Candidate]:
    # shortcut: up to 20 FTS queries per scan, move to embeddings with INK-138
    out = []
    for c in [c for c in chunks if c["text"]][:RELATED_CHUNKS]:
        q = _fts_or(c["text"])
        if q is None:
            continue
        try:
            reg = conn.execute(
                "SELECT region_id, r.document_id AS doc, -bm25(region_fts) AS score FROM region_fts"
                " JOIN regions r ON r.id = region_fts.region_id"
                " WHERE region_fts MATCH ? AND r.status='active' AND r.document_id != ?"
                " ORDER BY bm25(region_fts) LIMIT 1",
                (q, document_id),
            ).fetchone()
            ans = conn.execute(
                "SELECT question_id, -bm25(answer_fts) AS score FROM answer_fts"
                " WHERE answer_fts MATCH ? ORDER BY bm25(answer_fts) LIMIT 1",
                (q,),
            ).fetchone()
        except sqlite3.OperationalError:
            continue
        best = max((h for h in (reg, ans) if h is not None), key=lambda h: h["score"], default=None)
        if best is None or best["score"] < RELATED_MIN_SCORE:
            continue
        if best is reg:
            payload = {
                "action": "link",
                "other_document": reg["doc"],
                "other_chunk": reg["region_id"],
                "key": reg["region_id"],
            }
        else:
            payload = {
                "action": "link",
                "other_question": ans["question_id"],
                "key": ans["question_id"],
            }
        out.append(_cand("related", c["id"], payload, "Related note elsewhere"))
    return out


def run(conn: sqlite3.Connection, document_id: str, session_start: str = "") -> list[dict]:
    """Create offers for new candidates, best first. Returns the rows the budget expired."""
    seen = {
        _seen_key(o["kind"], o["anchor_chunk"], o["payload"].get("key"))
        for o in offers_db.list_offers(conn, document_id)
        if o["status"] != "expired"  # budget or TTL expiry is not a refusal: it may come back
    }
    changed: list[dict] = []
    for c in scan(conn, document_id):
        k = _seen_key(c.kind, c.anchor, c.payload.get("key"))
        if k in seen:
            continue
        try:
            _, expired = offers_db.create_offer(
                conn,
                document_id,
                kind=c.kind,
                anchor_chunk=c.anchor,
                reason=c.reason,
                payload=c.payload,
                score=c.score,
                source="detector",
                session_start=session_start,
            )
        except (offers_db.BudgetFull, offers_db.KindMuted, offers_db.AnchorUnknown):
            continue
        seen.add(k)
        changed += expired
    return changed


def _markup(conn: sqlite3.Connection, document_id: str, all_chunks: list[dict]) -> list[Candidate]:
    # decision 0102: only accepted diagrams, ink in the window after Accept, one offer per burst
    out = []
    for d in diagrams_db.list_accepted(conn, document_id):
        ink = markup.ink_over(conn, d)
        if not ink:
            continue
        ids = {e["id"] for e in markup.diagram_elements(conn, d)}
        anchor = next(
            (c for c in all_chunks if c["source"] == "agent" and ids & set(c["element_ids"])), None
        )
        if anchor is None:
            continue
        first = min(ink, key=lambda t: t[0])[1]["id"]
        payload = {"action": "diagram", "diagram": d["id"], "markup": True, "key": f"{d['id']}:{first}"}
        out.append(_cand("markup", anchor["id"], payload, "Apply mark-up?"))
    return out
