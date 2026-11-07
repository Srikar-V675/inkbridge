"""INK-130: offers table, budget, mute, expiry, focus."""

from datetime import UTC, datetime, timedelta

import pytest

from inkbridge import db
from inkbridge.db import offers as o


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "o.db"
    db.init_db(path)
    c = db.connect(path)
    c.execute(
        "INSERT INTO regions (id, document_id, created_by, status) VALUES ('c1','default','auto','active')"
    )
    c.commit()
    yield c
    c.close()


def mk(conn, score=0.5, kind="related", **kw):
    return o.create_offer(
        conn, "default", kind=kind, anchor_chunk="c1", reason="r", payload={}, score=score, **kw
    )


def test_budget_replaces_weakest(conn):
    first = [mk(conn, s)[0] for s in (0.3, 0.5, 0.7)]
    offer, changed = mk(conn, 0.9)
    assert [c["id"] for c in changed] == [first[0]["id"]]
    assert changed[0]["status"] == "expired" and changed[0]["resolved_at"]
    assert offer["status"] == "open"
    assert len(o.open_offers(conn, "default")) == 3
    with pytest.raises(o.BudgetFull):
        mk(conn, 0.1)
    assert len(o.list_offers(conn, "default")) == 4


def test_mute_after_two_dismissals(conn):
    for _ in range(2):
        o.dismiss_offer(conn, mk(conn)[0]["id"])
    with pytest.raises(o.KindMuted):
        mk(conn)
    mk(conn, kind="other")
    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    mk(conn, session_start=later)


def test_expiry_24h(conn):
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    conn.execute(
        "INSERT INTO offers (id, document_id, kind, anchor_chunk, reason, score, created_at)"
        " VALUES ('old','default','k','c1','r',0.5,?)",
        (old,),
    )
    conn.commit()
    swept: list[dict] = []
    rows = o.list_offers(conn, "default", "open", swept)
    assert rows == [] and [s["id"] for s in swept] == ["old"]
    assert o.get_offer(conn, "old")["status"] == "expired"


def test_focus_flag_roundtrip(conn):
    assert o.get_focus(conn, "default") is False
    assert o.set_focus(conn, "default", True) is True
    assert o.get_focus(conn, "default") is True
    with pytest.raises(db.DocumentNotFound):
        o.set_focus(conn, "nope", True)


def test_tap_dismiss_require_open(conn):
    a = mk(conn)[0]
    assert o.tap_offer(conn, a["id"])["status"] == "tapped"
    with pytest.raises(o.InvalidTransition) as e:
        o.tap_offer(conn, a["id"])
    assert e.value.current == "tapped"
    with pytest.raises(o.InvalidTransition):
        o.dismiss_offer(conn, a["id"])
    with pytest.raises(o.OfferNotFound):
        o.get_offer(conn, "zzz")


def test_unknown_anchor(conn):
    with pytest.raises(o.AnchorUnknown):
        o.create_offer(
            conn, "default", kind="k", anchor_chunk="nope", reason="r", payload={}, score=0.5
        )
