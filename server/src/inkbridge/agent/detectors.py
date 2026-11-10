"""Rule detectors that propose offers with no model call (INK-132, decision 0091).

Pure rules over the stored chunks; the caller (`run`, below) turns candidates into offers.
"""

import itertools
import json
import logging
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from inkbridge import db
from inkbridge.agent import markup
from inkbridge.canvas.sketch import read_sketch
from inkbridge.db import diagrams as diagrams_db
from inkbridge.db import offers as offers_db

log = logging.getLogger("inkbridge.offers")

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
RECENT_S = 120.0  # "just written" window, hypothesis (INK-197, decision 0112)


def _recent(c: dict, now: datetime) -> bool:
    # updated_at moves only when the ink changes (db/chunks.py), so it is the "just written" signal
    try:
        return now - datetime.fromisoformat(c["updated_at"]) <= timedelta(seconds=RECENT_S)
    except (KeyError, TypeError, ValueError):
        return False


STABLE_S = 2.0  # chunk ink unchanged this long before a question/equation offer (INK-199), hypothesis


def _stable(c: dict, now: datetime) -> bool:
    # updated_at moves only when the ink changes (see _recent)
    try:
        return now - datetime.fromisoformat(c["updated_at"]) >= timedelta(seconds=STABLE_S)
    except (KeyError, TypeError, ValueError):
        return False


def _complete(text: str) -> bool:
    t = text.strip()
    return t.endswith(("?", "=")) or len(t.split()) >= 2


@dataclass(frozen=True)
class Candidate:
    kind: str
    anchor: str
    score: float
    payload: dict
    reason: str  # at most 8 words


def _cand(kind: str, anchor: str, payload: dict, reason: str) -> Candidate:
    return Candidate(kind, anchor, SCORE[kind], payload, reason)


def _question_shaped(c: dict) -> bool:
    text = (c["text"] or "").strip()
    return bool(text) and bool(_QUESTION.match(text) or text.endswith("?"))


def _equation_shaped(c: dict) -> bool:
    return any(t and t.strip().endswith("=") for t in (c["text"], c["latex"]))


def _question(c: dict, now: datetime) -> Candidate | None:
    if _question_shaped(c) and _stable(c, now) and _complete(c["text"]):
        payload = {"action": "answer", "prepare": True, "key": c["text_hash"]}
        return _cand("question", c["id"], payload, "Looks like a question")


def _open_equation(c: dict, now: datetime) -> Candidate | None:
    if _equation_shaped(c) and _stable(c, now):
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


DANGLE_TOL = 80.0  # scene units; hypothesis, tune on logs (was 40, INK-197)
DANGLE_MIN_LEN = 150.0  # scene units; a short arrow is a stroke, not a flow (INK-197)
DANGLE_STRAIGHT = 0.9  # chord / path length; a curvy stroke is handwriting (INK-197)


def _long_straight_headed(e: dict, pts: list) -> bool:
    if not e.get("endArrowhead"):
        return False
    path = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in itertools.pairwise(pts))
    chord = ((pts[-1][0] - pts[0][0]) ** 2 + (pts[-1][1] - pts[0][1]) ** 2) ** 0.5
    return chord >= DANGLE_MIN_LEN and path > 0 and chord / path >= DANGLE_STRAIGHT


def _gap(x: float, y: float, s: dict) -> float:
    # distance from a point to the element's axis-aligned box; rotation ignored (decision 0107)
    sx, sy = s.get("x", 0.0), s.get("y", 0.0)
    dx = max(sx - x, 0.0, x - (sx + s.get("width", 0.0)))
    dy = max(sy - y, 0.0, y - (sy + s.get("height", 0.0)))
    return (dx * dx + dy * dy) ** 0.5


def _free_end_arrows(
    conn: sqlite3.Connection, document_id: str, chunks: list[dict]
) -> list[Candidate]:
    """Chunker v1 keeps arrows in no chunk kind of their own: find a native arrow whose tip touches nothing."""
    elements = json.loads(db.get_scene(conn, document_id)[1])
    live = [
        e
        for e in elements
        if not e.get("isDeleted")
        and not (isinstance(e.get("customData"), dict) and e["customData"].get("draft"))
    ]
    owner = {i: c for c in chunks for i in c["element_ids"]}
    solids = [e for e in live if e.get("type") not in ("arrow", "line")]
    out = []
    for e in live:
        pts = e.get("points") or []
        if e.get("type") != "arrow" or len(pts) < 2 or (e.get("endBinding") or {}).get("elementId"):
            continue
        if not _long_straight_headed(e, pts):
            continue
        ex, ey = e["x"] + pts[-1][0], e["y"] + pts[-1][1]
        if any(_gap(ex, ey, s) <= DANGLE_TOL for s in solids if s["id"] != e["id"]):
            continue
        c = owner.get(e["id"]) or owner.get((e.get("startBinding") or {}).get("elementId"))
        if c is None:
            log.debug("free arrow %s belongs to no active chunk", e["id"])
            continue
        out.append(
            _cand(
                "dangling_arrow",
                c["id"],
                {"action": "ask_user", "key": e["id"]},
                "Arrow leads nowhere",
            )
        )
    return out


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
    return [
        _cand(
            "to_note", biggest["id"], {"action": "note", "key": "canvas"}, "Turn this into a note"
        )
    ]


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


def held_unstable(conn: sqlite3.Connection, document_id: str) -> bool:
    """True when a fresh chunk would give a question/equation offer but its ink is still changing."""
    now = datetime.now(UTC)
    for c in db.list_regions(conn, document_id, chunks=True, status="active", limit=500):
        if c["source"] == "agent" or _tiny(c) or not _recent(c, now) or _stable(c, now):
            continue
        if _question_shaped(c) or _equation_shaped(c):
            return True
    return False


def scan_counts(conn: sqlite3.Connection, document_id: str) -> str:
    """One log fragment: how many chunks the scan sees, how many have no reading, how many candidates."""
    all_chunks = db.list_regions(conn, document_id, chunks=True, status="active", limit=500)
    chunks = [c for c in all_chunks if c["source"] != "agent"]
    unread = sum(1 for c in chunks if not (c["text"] or "").strip())
    cands = Counter(c.kind for c in scan(conn, document_id))
    return f"chunks={len(chunks)} unread={unread} candidates={sum(cands.values())} {dict(cands)}"


def scan(conn: sqlite3.Connection, document_id: str, slow: bool = False) -> list[Candidate]:
    # slow=True adds the on-request candidates (to_note, related); nothing in the API passes it (INK-197)
    all_chunks = db.list_regions(conn, document_id, chunks=True, status="active", limit=500)
    chunks = [
        c for c in all_chunks if c["source"] != "agent" and not _tiny(c)
    ]  # an agent's answer never triggers
    watches = db.list_watches(conn, document_id)
    now = datetime.now(UTC)
    fresh = [c for c in chunks if _recent(c, now)]  # old ink never gets a new offer (INK-197)
    fresh_ids = {c["id"] for c in fresh}
    out: list[Candidate] = []
    for c in fresh:
        out += [x for x in (_question(c, now), _open_equation(c, now), _dangling(c)) if x]
    out += [x for x in _free_end_arrows(conn, document_id, fresh) if x.anchor in fresh_ids]
    out += _stale_note(chunks, watches)
    if slow:
        out += _to_note(chunks, watches)
    out += _stale_diagram(conn, document_id, chunks)
    out += _sketch(conn, document_id, fresh)
    if slow:
        out += _related(conn, document_id, chunks)
    out += _markup(conn, document_id, all_chunks)
    first: dict[tuple, Candidate] = {}
    for c in out:  # a v2 connector chunk and a scene arrow never give two for one anchor
        first.setdefault((c.kind, c.anchor) if c.kind == "dangling_arrow" else id(c), c)
    return sorted(first.values(), key=lambda c: -c.score)


def _stale_diagram(
    conn: sqlite3.Connection, document_id: str, chunks: list[dict]
) -> list[Candidate]:
    # shortcut: a chunk replaced by a new id is skipped (no successor follow), see decision 0100
    by_id = {c["id"]: c for c in chunks}
    out = []
    for d in diagrams_db.list_accepted(conn, document_id):
        for snap in d["from_chunks"]:
            c = by_id.get(snap["chunk"])
            if (
                c is None
                or snap["text_hash"] is None
                or c["text_hash"] in (None, snap["text_hash"])
            ):
                continue
            payload = {
                "action": "diagram",
                "diagram": d["id"],
                "key": f"{d['id']}:{c['text_hash']}",
            }
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


def run(conn: sqlite3.Connection, document_id: str, session_start: str = "", slow: bool = False) -> list[dict]:
    """Create offers for new candidates, best first. Returns the rows the budget expired."""
    seen = {
        _seen_key(o["kind"], o["anchor_chunk"], o["payload"].get("key"))
        for o in offers_db.list_offers(conn, document_id)
        if o["status"] != "expired"  # budget or TTL expiry is not a refusal: it may come back
    }
    changed: list[dict] = []
    if offers_db.open_offers(conn, document_id):  # one chip on screen at a time (INK-197)
        log.info("detector run doc=%s held=open_offer", document_id)
        return changed
    candidates = scan(conn, document_id, slow=slow)
    created: Counter = Counter()
    skipped: Counter = Counter()
    for c in candidates:
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
        except (offers_db.BudgetFull, offers_db.KindMuted, offers_db.AnchorUnknown) as e:
            reason = {"BudgetFull": "budget_full", "KindMuted": "kind_muted"}.get(
                type(e).__name__, "anchor_unknown"
            )
            skipped[f"{c.kind}:{reason}"] += 1
            continue
        created[c.kind] += 1
        seen.add(k)
        changed += expired
        break  # best candidate first; the rest are found again on a later scan while the ink is fresh
    log.info(
        "detector run doc=%s candidates=%d created=%s skipped=%s",
        document_id,
        len(candidates),
        dict(created),
        dict(skipped),
    )
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
        payload = {
            "action": "diagram",
            "diagram": d["id"],
            "markup": True,
            "key": f"{d['id']}:{first}",
        }
        out.append(_cand("markup", anchor["id"], payload, "Apply mark-up?"))
    return out
