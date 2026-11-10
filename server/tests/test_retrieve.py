"""INK-136: retrieval across canvases (keyword first), decision 0079."""

import shutil

import pytest

from inkbridge import db
from inkbridge.db import retrieve as retrieve_db
from tests.fts_check import fts_problems
from tests.test_chunk_persistence import row
from tests.test_questions_api import answer, ask


def test_migration_0010_backfills_answered_questions(tmp_path, monkeypatch):
    old = tmp_path / "old"
    old.mkdir()
    for f in sorted(db.MIGRATIONS_DIR.glob("000[1-7]_*.sql")):
        shutil.copy(f, old / f.name)
    monkeypatch.setattr(db.migrations, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "v7.db")
    db.migrate(conn)
    db.ensure_default_document(conn)
    conn.execute(
        "INSERT INTO questions (id, document_id, text, answer_md, status, created_at)"
        " VALUES ('q1','default','why?','because zebras','answered','t')"
    )
    conn.execute(
        "INSERT INTO questions (id, document_id, text, status, created_at)"
        " VALUES ('q2','default','pending?','pending','t')"
    )
    conn.commit()
    monkeypatch.undo()
    assert 10 in db.migrate(conn)
    rows = conn.execute("SELECT question_id, question, answer FROM answer_fts").fetchall()
    assert [tuple(r) for r in rows] == [("q1", "why?", "because zebras")]
    conn.close()


def test_answering_indexes_and_cancel_does_not(client):
    done, cancelled = ask(client)["id"], ask(client, "never answered")["id"]
    assert answer(client, done, "photosynthesis notes").status_code == 200
    assert client.post(f"/questions/{cancelled}/cancel").status_code == 200
    conn = db.connect()
    try:
        ids = [r["question_id"] for r in conn.execute("SELECT question_id FROM answer_fts")]
    finally:
        conn.close()
    assert ids == [done]


def test_answer_fts_detector_bites(client):
    qid = ask(client)["id"]
    assert answer(client, qid, "some answer").status_code == 200
    conn = db.connect()
    try:
        assert fts_problems(conn) == []
        conn.execute("DELETE FROM answer_fts WHERE question_id = ?", (qid,))
        assert any(qid in p for p in fts_problems(conn))
        conn.execute(
            "INSERT INTO answer_fts (question_id, document_id, question, answer)"
            " VALUES (?, 'default', 'why?', 'some answer')",
            (qid,),
        )
        assert fts_problems(conn) == []
    finally:
        conn.close()


def canvas_with_reading(client, title, text, *, prefix="a", source="gemini"):
    doc = client.post("/documents", json={"title": title}).json()["id"]
    elements = row(prefix, 3)
    r = client.put(f"/documents/{doc}/scene", json={"base_version": 0, "elements": elements})
    assert r.status_code == 200, r.text
    (chunk,) = client.get(f"/documents/{doc}/regions", params={"chunks": True}).json()
    conn = db.connect()
    try:
        db.save_recognition(conn, chunk["id"], chunk["content_hash"], source, text)
    finally:
        conn.close()
    return doc, chunk["id"]


def retrieve(client, q, **params):
    r = client.get("/retrieve", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()["results"]


@pytest.fixture
def two(client):
    a = canvas_with_reading(client, "Optimisation", "gradient descent notes", prefix="a")
    b = canvas_with_reading(client, "Calculus", "gradient of the loss", prefix="b")
    return a, b


def test_scope_all_finds_hits_in_other_canvases(client, two):
    (da, ca), (db_, cb) = two
    hits = {h["canvas"]: h for h in retrieve(client, "gradient", scope="all")}
    assert set(hits) == {da, db_}
    for doc, chunk, title in ((da, ca, "Optimisation"), (db_, cb, "Calculus")):
        h = hits[doc]
        assert (h["kind"], h["id"], h["chunk_id"], h["canvas_title"]) == (
            "chunk",
            chunk,
            chunk,
            title,
        )
        assert f"?canvas={doc}&chunk={chunk}" in h["deep_link"]
        assert h["source"] == "gemini" and "[gradient]" in h["snippet"]
        assert h["matched_by"] == ["chunks_fts"] and h["score"] > 0


def test_scope_canvas_filters_to_one_canvas(client, two):
    (da, _), _ = two
    assert [h["canvas"] for h in retrieve(client, "gradient", scope="canvas", document_id=da)] == [
        da
    ]
    assert retrieve(client, "gradient") == []  # default scope is canvas, default document "default"


def test_unknown_canvas_is_404(client):
    r = client.get("/retrieve", params={"q": "x", "scope": "canvas", "document_id": "nope"})
    assert r.status_code == 404


def test_bad_scope_and_k_are_422(client):
    assert client.get("/retrieve", params={"q": "x", "scope": "world"}).status_code == 422
    assert client.get("/retrieve", params={"q": "x", "k": 0}).status_code == 422
    assert client.get("/retrieve", params={"q": "x", "k": 51}).status_code == 422


def test_archived_canvas_skipped_under_all_only(client, two):
    (da, _), (db_, _) = two
    assert client.patch(f"/documents/{da}", json={"archived": True}).status_code == 200
    assert {h["canvas"] for h in retrieve(client, "gradient", scope="all")} == {db_}
    assert [h["canvas"] for h in retrieve(client, "gradient", scope="canvas", document_id=da)] == [
        da
    ]


def test_orphaned_chunk_not_returned(client):
    doc, _ = canvas_with_reading(client, "Gone", "gradient descent")
    gone = [{**e, "isDeleted": True, "version": e["version"] + 1} for e in row("a", 3)]
    version = client.get(f"/documents/{doc}/scene").json()["version"]
    r = client.put(f"/documents/{doc}/scene", json={"base_version": version, "elements": gone})
    assert r.status_code == 200, r.text
    assert retrieve(client, "gradient", scope="all") == []


NOTE = {"type": "note", "path": "content/library/zebra-notes.md"}


def test_answers_are_retrieved_and_carry_their_chunk(client):
    doc, chunk = canvas_with_reading(client, "Plants", "leaf diagram")
    q = client.post(f"/documents/{doc}/questions", json={"text": "what is this?"}).json()["id"]
    sources = [{"type": "chunk", "id": chunk}, NOTE]
    assert answer(client, q, "the answer is photosynthesis", sources).status_code == 200
    (h,) = retrieve(client, "photosynthesis", scope="all")
    assert (h["kind"], h["id"], h["chunk_id"], h["source"]) == ("answer", q, chunk, "answer")
    assert h["canvas"] == doc and f"&chunk={chunk}" in h["deep_link"]
    assert h["matched_by"] == ["answers_fts"]
    q2 = client.post(f"/documents/{doc}/questions", json={"text": "another?"}).json()["id"]
    assert answer(client, q2, "also chlorophyll", [NOTE]).status_code == 200
    (h2,) = retrieve(client, "chlorophyll", scope="all")
    assert h2["chunk_id"] is None and h2["deep_link"].endswith(f"?canvas={doc}")


def test_no_vault_text_in_the_index(client):
    doc, _ = canvas_with_reading(client, "Plants", "leaf diagram")
    q = client.post(f"/documents/{doc}/questions", json={"text": "what?"}).json()["id"]
    assert answer(client, q, "the answer is photosynthesis", [NOTE]).status_code == 200
    assert retrieve(client, "zebra", scope="all") == []
    conn = db.connect()
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(answer_fts)")]
        assert cols == ["question_id", "document_id", "question", "answer"]
        for table in ("region_fts", "answer_fts"):
            assert not conn.execute(f"SELECT 1 FROM {table} WHERE {table} MATCH 'zebra'").fetchall()
    finally:
        conn.close()


def test_rrf_orders_by_rank_sum():
    x, y, z = ("chunk", "x"), ("chunk", "y"), ("chunk", "z")
    out = retrieve_db.rrf({"a": [x, y], "b": [y, z]})
    assert [k for k, _, _ in out] == [y, x, z]
    assert out[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert out[0][2] == ["a", "b"]
    assert [k for k, _, _ in retrieve_db.rrf({"a": [z], "b": [x]})] == [x, z]  # tie: by key


def test_extra_ranker_changes_nothing_else(client, two, monkeypatch):
    (_, ca), _ = two
    before = retrieve(client, "gradient", scope="all")

    def fake(conn, query, document_id, limit):
        h = next(h for h in before if h["id"] == ca)
        return [
            {
                "kind": "chunk",
                "id": ca,
                "canvas": h["canvas"],
                "canvas_title": h["canvas_title"],
                "snippet": "x",
                "key": ("chunk", ca),
            }
        ]

    monkeypatch.setitem(retrieve_db.RANKERS, "semantic", fake)
    after = retrieve(client, "gradient", scope="all")
    assert after[0]["id"] == ca and "semantic" in after[0]["matched_by"]
    assert {h["id"] for h in after} == {h["id"] for h in before}
    assert all(set(h) == set(before[0]) for h in after)


def test_empty_or_symbol_query_returns_nothing(client, two):
    assert retrieve(client, "!!!", scope="all") == []
