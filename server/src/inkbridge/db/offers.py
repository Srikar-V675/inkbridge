"""Offers beside the ink (INK-130, decision 0089): budget, mute, expiry, focus. Pure sqlite."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from inkbridge.db import tasks as tasks_db
from inkbridge.db.common import DocumentNotFound, _now

OFFER_BUDGET = 3
OFFER_TTL_S = 24 * 3600
MUTE_AFTER = 2


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
    """Caller owns the transaction. Returns the rows it just expired; the API layer publishes."""
    cutoff = (datetime.now(UTC) - timedelta(seconds=OFFER_TTL_S)).isoformat()
    rows = conn.execute(
        "UPDATE offers SET status='expired', resolved_at=? WHERE document_id=? AND status='open'"
        " AND created_at < ? RETURNING id",
        (_now(), document_id, cutoff),
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
