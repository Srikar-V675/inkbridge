"""Offers routes and the push gate (INK-130, decision 0089).

Offers are stored whenever they are created; `flush` pushes `offer.created` only while the user's
attention allows it and Focus is off. Updates reach the browser only for offers it was sent.
"""

import logging
import threading
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from inkbridge import config, db
from inkbridge.agent import attention as attention_mod
from inkbridge.agent import detectors, latest_ink
from inkbridge.api.deps import Conn
from inkbridge.api.ws import hub, updated_message
from inkbridge.db import offers as offers_db
from inkbridge.db import supersede

router = APIRouter()
log = logging.getLogger("inkbridge.offers")

pushed: dict[str, set[str]] = {}  # document -> offer ids this process sent to a browser
_seen_session: dict[str, str] = {}
_timers: dict[str, threading.Timer] = {}
_ARM_TIMERS = True
DETECT_DEBOUNCE_S = 2.0  # hypothesis (decision 0091)
_scans: dict[str, threading.Timer] = {}
_scan_lock = threading.Lock()  # guards _scans
_scan_locks: dict[str, threading.Lock] = {}  # one running scan per document


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfferIn(_Strict):
    kind: str = Field(min_length=1, max_length=64)
    anchor_chunk: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
    score: float = Field(ge=0, le=1)
    source: Literal["triage", "detector", "agent"] = "triage"


class FocusIn(_Strict):
    on: bool


def _arm(document_id: str, wait: float) -> threading.Timer:
    t = threading.Timer(wait + 0.05, flush, [document_id])
    t.daemon = True
    t.start()
    return t


def flush(document_id: str) -> None:
    """Push open offers if the gate is open; otherwise arm one timer for the rest of the quiet window."""
    if not config.offers_enabled():
        return
    t = _timers.pop(document_id, None)
    if t:
        t.cancel()
    session = hub.session_start(document_id)
    if _seen_session.get(document_id) != session:  # a new page: it gets everything again
        _seen_session[document_id] = session
        pushed[document_id] = set()
    conn = db.connect()
    try:
        swept: list[dict] = []
        offers_db.list_offers(conn, document_id, "open", swept)
        publish_updates(swept)  # the chip goes away when its offer lapses (INK-205)
        if offers_db.get_focus(conn, document_id):
            log.info("offers held doc=%s reason=focus", document_id)
            return
        gate = attention_mod.attention
        if not gate.can_push(document_id):
            wait = gate.remaining(document_id)
            state = gate.state(document_id)
            reason = {"none": "no_attention", "pen_down": "pen_down"}.get(
                state, f"quiet_{wait or 0:.0f}s"
            )
            log.info("offers held doc=%s reason=%s", document_id, reason)
            if wait and _ARM_TIMERS:
                _timers[document_id] = _arm(document_id, wait)
            return
        sent = pushed.setdefault(document_id, set())
        rows = [o for o in offers_db.open_offers(conn, document_id) if o["id"] not in sent]
    finally:
        conn.close()
    for o in rows:
        pushed[document_id].add(o["id"])
        hub.publish(document_id, {"type": "offer.created", "offer": o})


def publish_updates(rows: list[dict]) -> None:
    for o in rows:
        if o["id"] in pushed.get(o["document_id"], ()):
            hub.publish(o["document_id"], {"type": "offer.updated", "offer": o})


def scan_now(document_id: str) -> None:
    """Run the detectors on their own connection and push what they made. Never raises."""
    if not config.offers_enabled():
        return
    with _scan_lock:
        if _scans.get(document_id) is threading.current_thread():
            del _scans[document_id]  # this timer is running now, not pending
        lock = _scan_locks.setdefault(document_id, threading.Lock())
    try:
        with lock:  # seen-check and create_offer are separate: two scans would duplicate
            conn = db.connect()
            try:
                log.info("scan doc=%s %s", document_id, detectors.scan_counts(conn, document_id))
                superseded, ops = supersede.run(conn, document_id)
                extra = []
                if latest_ink.enabled():
                    gate = attention_mod.attention
                    if gate.state(document_id) == "quiet" and gate.can_push(document_id):
                        extra = latest_ink.poll(conn, document_id)
                        if not extra and latest_ink.pending(conn, document_id):
                            schedule_scan(document_id)  # throttled or dropped: look again later
                    elif gate.state(document_id) != "none" and latest_ink.pending(
                        conn, document_id
                    ):
                        schedule_scan(document_id)  # wait out the quiet window
                changed = detectors.run(
                    conn, document_id, hub.session_start(document_id), extra=extra
                )
                if detectors.held_unstable(conn, document_id):
                    schedule_scan(document_id)  # ink still changing: look again (INK-199)
            finally:
                conn.close()
        publish_updates(superseded + changed)
        for op in ops:
            hub.publish(document_id, updated_message(op))
        flush(document_id)
    except Exception:
        log.exception("detector scan failed doc=%s", document_id)


def schedule_scan(document_id: str) -> None:
    """Debounce: each save or reading re-arms one timer, so a burst scans once, off the save path."""
    if not _ARM_TIMERS or not config.offers_enabled():
        return
    with _scan_lock:
        old = _scans.pop(document_id, None)
        if old:
            old.cancel()
        t = threading.Timer(DETECT_DEBOUNCE_S, scan_now, [document_id])
        t.daemon = True
        t.start()
        _scans[document_id] = t


def publish_chunks(document_id: str, msg: dict) -> None:
    hub.publish(document_id, msg)
    schedule_scan(document_id)


@router.post("/documents/{document_id}/offers", status_code=201)
def create_offer(document_id: str, body: OfferIn, conn: Conn) -> dict:
    try:
        offer, changed = offers_db.create_offer(
            conn,
            document_id,
            **body.model_dump(),
            session_start=hub.session_start(document_id),
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except offers_db.BudgetFull:
        raise HTTPException(409, {"code": "budget_full"}) from None
    except offers_db.KindMuted:
        raise HTTPException(409, {"code": "kind_muted"}) from None
    except offers_db.AnchorUnknown:
        raise HTTPException(422, {"code": "anchor_unknown"}) from None
    publish_updates(changed)
    flush(document_id)
    return offer


@router.get("/documents/{document_id}/offers")
def list_offers(
    document_id: str,
    conn: Conn,
    status: Annotated[
        Literal["open", "tapped", "dismissed", "expired", "done"] | None, Query()
    ] = None,
) -> dict:
    if not db.document_exists(conn, document_id):
        raise HTTPException(404, "document not found")
    swept: list[dict] = []
    rows = offers_db.list_offers(conn, document_id, status, swept)
    publish_updates(swept)
    waiting = 0
    focus = offers_db.get_focus(conn, document_id)
    if status in (None, "open") and focus:
        waiting = sum(1 for o in rows if o["status"] == "open")
        rows = [o for o in rows if o["status"] != "open"]
    return {"offers": rows, "waiting": waiting, "focus": focus}


def _resolve(fn, offer_id: str, conn) -> dict:
    try:
        offer = fn(conn, offer_id)
    except offers_db.OfferNotFound:
        raise HTTPException(404, "offer not found") from None
    except offers_db.InvalidTransition as e:
        raise HTTPException(409, {"code": "invalid_transition", "status": e.current}) from None
    publish_updates([offer])
    return offer


@router.post("/offers/{offer_id}/tap")
def tap(offer_id: str, conn: Conn) -> dict:
    return _resolve(offers_db.tap_offer, offer_id, conn)


@router.post("/offers/{offer_id}/dismiss")
def dismiss(offer_id: str, conn: Conn) -> dict:
    return _resolve(offers_db.dismiss_offer, offer_id, conn)


@router.put("/documents/{document_id}/focus")
def set_focus(document_id: str, body: FocusIn, conn: Conn) -> dict:
    try:
        offers_db.set_focus(conn, document_id, body.on)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    if not body.on:
        flush(document_id)
    return {"on": body.on}
