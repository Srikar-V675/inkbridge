"""Offers beside the ink (INK-130, decision 0089): budget, mute, expiry, focus. Pure sqlite."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from inkbridge import config
from inkbridge.db import tasks as tasks_db
from inkbridge.db.common import DocumentNotFound, _now

OFFER_BUDGET = 3
OFFER_TTL_S = 24 * 3600
MUTE_AFTER = 2
PROACTIVE = ("question", "open_equation", "dangling_arrow", "sketch")  # short open TTL (INK-205)
_LAPSED = (
    "payload_json = json_set(COALESCE(NULLIF(payload_json, ''), '{}'), '$.lapsed', json('true'))"
)
_PRO_SQL = ",".join("?" * len(PROACTIVE))


class OfferNotFound(Exception):
    pass


class BudgetFull(Exception):
    pass


class KindMuted(Exception):
    pass


class AnchorUnknown(Exception):
    pass


class InvalidTransition(Exception):
    def __init__(self, current: str):
        super().__init__(current)
        self.current = current


def _dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    return d


def get_offer(conn: sqlite3.Connection, offer_id: str) -> dict:
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    if row is None:
        raise OfferNotFound(offer_id)
    return _dict(row)


def _expire_stale(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Caller owns the transaction. Returns the rows it just expired; the API layer publishes.

    Open proactive offers lapse after OFFER_OPEN_TTL_S (marked `lapsed`, so the same ink is not
    offered again); everything else after 24 h. Expiry is never a dismissal (INK-205)."""
    now = datetime.now(UTC)
    short = (now - timedelta(seconds=config.offer_open_ttl_s())).isoformat()
    long = (now - timedelta(seconds=OFFER_TTL_S)).isoformat()
    rows = conn.execute(
        f"UPDATE offers SET status='expired', resolved_at=?, {_LAPSED} WHERE document_id=?"
        f" AND status='open' AND kind IN ({_PRO_SQL}) AND created_at < ? RETURNING id",
        (_now(), document_id, *PROACTIVE, short),
    ).fetchall()
    rows += conn.execute(
        "UPDATE offers SET status='expired', resolved_at=? WHERE document_id=? AND status='open'"
        " AND created_at < ? RETURNING id",
        (_now(), document_id, long),
    ).fetchall()
    return [get_offer(conn, r["id"]) for r in rows]


def _sweep(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    if conn.in_transaction:
        return _expire_stale(conn, document_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        swept = _expire_stale(conn, document_id)
        conn.commit()
        return swept
    except BaseException:
        conn.rollback()
        raise


def _muted(conn, document_id, kind, session_start) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) FROM offers WHERE document_id=? AND kind=? AND status='dismissed'"
        " AND resolved_at >= ?",
        (document_id, kind, session_start),
    ).fetchone()[0]
    return n >= MUTE_AFTER


def create_offer(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    kind: str,
    anchor_chunk: str,
    reason: str,
    payload: dict,
    score: float,
    source: str = "triage",
    session_start: str = "",
    replace_open: bool = False,
) -> tuple[dict, list[dict]]:
    """Returns (offer, changed) where changed = rows expired by the sweep or replaced by the budget."""
    if conn.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone() is None:
        raise DocumentNotFound(document_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        changed = _expire_stale(conn, document_id)
        if (
            conn.execute(
                "SELECT 1 FROM regions WHERE id=? AND document_id=? AND created_by='auto'"
                " AND status='active'",
                (anchor_chunk, document_id),
            ).fetchone()
            is None
        ):
            raise AnchorUnknown(anchor_chunk)
        if _muted(conn, document_id, kind, session_start):
            raise KindMuted(kind)
        now = _now()
        if replace_open:  # newer ink beats an open proactive offer, in this transaction (INK-205)
            for r in conn.execute(
                f"UPDATE offers SET status='expired', resolved_at=?, {_LAPSED} WHERE document_id=?"
                f" AND status='open' AND kind IN ({_PRO_SQL}) RETURNING id",
                (now, document_id, *PROACTIVE),
            ).fetchall():
                changed.append(get_offer(conn, r["id"]))
        open_rows = conn.execute(
            "SELECT id, score FROM offers WHERE document_id=? AND status='open'"
            " ORDER BY score ASC, created_at ASC",
            (document_id,),
        ).fetchall()
        if len(open_rows) >= OFFER_BUDGET:
            weakest = open_rows[0]
            if score <= weakest["score"]:
                raise BudgetFull(document_id)
            conn.execute(
                "UPDATE offers SET status='expired', resolved_at=? WHERE id=?",
                (now, weakest["id"]),
            )
            changed.append(get_offer(conn, weakest["id"]))
        oid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO offers (id, document_id, kind, anchor_chunk, reason, payload_json, score,"
            " source, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (oid, document_id, kind, anchor_chunk, reason, json.dumps(payload), score, source, now),
        )
        offer = get_offer(conn, oid)
        conn.commit()
    except BaseException:
        conn.rollback()  # a refusal also undoes the sweep; it runs again next call
        raise
    return offer, changed


def sweep_all(conn: sqlite3.Connection) -> int:
    """Startup: expire every stale open offer in every canvas (INK-205). Returns how many."""
    docs = [
        r[0] for r in conn.execute("SELECT DISTINCT document_id FROM offers WHERE status='open'")
    ]
    return sum(len(_sweep(conn, d)) for d in docs)


def list_offers(
    conn: sqlite3.Connection,
    document_id: str,
    status: str | None = None,
    swept: list[dict] | None = None,
) -> list[dict]:
    rows = _sweep(conn, document_id)
    if swept is not None:
        swept.extend(rows)
    sql, args = "SELECT * FROM offers WHERE document_id=?", [document_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC, rowid DESC"
    return [_dict(r) for r in conn.execute(sql, args)]


def open_offers(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return list_offers(conn, document_id, "open")


def _resolve(conn: sqlite3.Connection, offer_id: str, status: str, after=None) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = get_offer(conn, offer_id)
        if cur["status"] != "open":
            raise InvalidTransition(cur["status"])
        conn.execute(
            "UPDATE offers SET status=?, resolved_at=? WHERE id=?", (status, _now(), offer_id)
        )
        if after:
            after(conn, cur)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_offer(conn, offer_id)


def tap_offer(conn: sqlite3.Connection, offer_id: str) -> dict:
    def make_task(conn: sqlite3.Connection, o: dict) -> None:
        task = tasks_db.create_task(
            conn,
            o["document_id"],
            "offer",
            offer_id=o["id"],
            input={
                "mode": tasks_db.OFFER_MODE.get(o["kind"], "question"),
                "offer_kind": o["kind"],
                "anchor_chunk": o["anchor_chunk"],
                "reason": o["reason"],
                "payload": o["payload"],
            },
        )
        conn.execute("UPDATE offers SET task_id=? WHERE id=?", (task["id"], o["id"]))

    return _resolve(conn, offer_id, "tapped", make_task)


def dismiss_offer(conn: sqlite3.Connection, offer_id: str) -> dict:
    return _resolve(conn, offer_id, "dismissed")


def get_focus(conn: sqlite3.Connection, document_id: str) -> bool:
    row = conn.execute("SELECT focus FROM documents WHERE id=?", (document_id,)).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return bool(row["focus"])


def set_focus(conn: sqlite3.Connection, document_id: str, on: bool) -> bool:
    get_focus(conn, document_id)
    conn.execute("UPDATE documents SET focus=? WHERE id=?", (int(on), document_id))
    conn.commit()
    return on
