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


def _backdate(conn, oid, seconds):
    ts = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    conn.execute("UPDATE offers SET created_at=? WHERE id=?", (ts, oid))
    conn.commit()


def test_open_proactive_offer_expires_after_60s_without_a_dismissal(conn):
    q = mk(conn, kind="question")[0]
    _backdate(conn, q["id"], 61)
    swept: list[dict] = []
    assert o.list_offers(conn, "default", "open", swept) == []
    assert [s["id"] for s in swept] == [q["id"]]
    assert o.get_offer(conn, q["id"])["status"] == "expired"
    for _ in range(3):  # expiry is not a dismissal: the kind is not muted
        x = mk(conn, kind="question")[0]
        _backdate(conn, x["id"], 61)
        o.list_offers(conn, "default")


def test_young_proactive_offer_stays_open(conn):
    q = mk(conn, kind="question")[0]
    _backdate(conn, q["id"], 30)
    assert [r["id"] for r in o.open_offers(conn, "default")] == [q["id"]]


def test_tapped_offer_is_never_swept(conn):
    q = mk(conn, kind="question")[0]
    o.tap_offer(conn, q["id"])
    _backdate(conn, q["id"], 3600)
    o.list_offers(conn, "default")
    assert o.get_offer(conn, q["id"])["status"] == "tapped"


def test_markup_and_note_offers_keep_24h(conn):
    ids = [mk(conn, kind=k)[0]["id"] for k in ("markup", "stale_note", "to_note")]
    for i in ids:
        _backdate(conn, i, 3600)
    assert len(o.open_offers(conn, "default")) == 3


def test_open_ttl_env(conn, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_OFFER_OPEN_TTL_S", "600")
    q = mk(conn, kind="question")[0]
    _backdate(conn, q["id"], 120)
    assert len(o.open_offers(conn, "default")) == 1


def test_replace_open_proactive_in_one_transaction(conn):
    old = mk(conn, kind="question")[0]
    keep = mk(conn, kind="markup")[0]
    new, changed = mk(conn, kind="open_equation", replace_open=True)
    assert [c["id"] for c in changed] == [old["id"]]
    assert changed[0]["status"] == "expired" and changed[0]["payload"]["lapsed"] is True
    assert {r["id"] for r in o.open_offers(conn, "default")} == {new["id"], keep["id"]}


def test_sweep_all_at_startup(conn):
    q = mk(conn, kind="question")[0]
    k = mk(conn, kind="markup")[0]
    _backdate(conn, q["id"], 90)
    _backdate(conn, k["id"], 90)
    assert o.sweep_all(conn) == 1
    assert o.get_offer(conn, q["id"])["status"] == "expired"
    assert o.get_offer(conn, k["id"])["status"] == "open"
