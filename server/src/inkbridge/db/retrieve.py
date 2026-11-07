"""Read-only retrieval over chunk readings and past answers (INK-136, decision 0079)."""

import json
import sqlite3
from collections.abc import Callable

from inkbridge.db.common import AUTO
from inkbridge.db.recognitions import _BEST_RECOGNITION, _fts_query

RRF_C = 60
CANDIDATES = 50
SCOPES = ("canvas", "all")

Key = tuple[str, str]


def rrf(lists: dict[str, list[Key]], c: int = RRF_C) -> list[tuple[Key, float, list[str]]]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1 / (c + rank), rank from 1."""
    score: dict[Key, float] = {}
    by: dict[Key, list[str]] = {}
    for name, keys in lists.items():
        for rank, key in enumerate(keys, start=1):
            score[key] = score.get(key, 0.0) + 1.0 / (c + rank)
            by.setdefault(key, []).append(name)
    return [(k, score[k], by[k]) for k in sorted(score, key=lambda k: (-score[k], k))]


def _scope(sql: str, args: list, column: str, document_id: str | None) -> tuple[str, list]:
    """canvas: that document. all (document_id None): every canvas that is not archived."""
    if document_id is not None:
        return sql + f" AND {column} = ?", [*args, document_id]
    return sql + " AND d.archived_at IS NULL", args


def _chunk_ranker(conn: sqlite3.Connection, query: str, document_id: str | None, limit: int) -> list[dict]:
    match = _fts_query(query)
    if match is None:
        return []
    sql = (
        "SELECT r.id AS id, r.document_id AS canvas, d.title AS canvas_title,"
        " r.content_hash AS content_hash,"
        " snippet(region_fts, -1, '[', ']', '…', 12) AS snippet"
        " FROM region_fts JOIN regions r ON r.id = region_fts.region_id"
        " JOIN documents d ON d.id = r.document_id"
        " WHERE region_fts MATCH ? AND r.status = 'active' AND r.created_by = ?"
    )
    sql, args = _scope(sql, [match, AUTO], "r.document_id", document_id)
    sql += " ORDER BY bm25(region_fts), r.id LIMIT ?"
    return [
        {**dict(h), "kind": "chunk", "key": ("chunk", h["id"])}
        for h in conn.execute(sql, [*args, limit])
    ]


def _answer_ranker(conn: sqlite3.Connection, query: str, document_id: str | None, limit: int) -> list[dict]:
    match = _fts_query(query)
    if match is None:
        return []
    sql = (
        "SELECT q.id AS id, q.document_id AS canvas, d.title AS canvas_title,"
        " q.sources_json AS sources_json,"
        " snippet(answer_fts, -1, '[', ']', '…', 12) AS snippet"
        " FROM answer_fts JOIN questions q ON q.id = answer_fts.question_id"
        " JOIN documents d ON d.id = q.document_id"
        " WHERE answer_fts MATCH ? AND q.status = 'answered'"
    )
    sql, args = _scope(sql, [match], "q.document_id", document_id)
    sql += " ORDER BY bm25(answer_fts), q.id LIMIT ?"
    return [
        {**dict(h), "kind": "answer", "key": ("answer", h["id"])}
        for h in conn.execute(sql, [*args, limit])
    ]


Ranker = Callable[[sqlite3.Connection, str, str | None, int], list[dict]]
RANKERS: dict[str, Ranker] = {"chunks_fts": _chunk_ranker, "answers_fts": _answer_ranker}
# INK-138 adds RANKERS["semantic"]; a ranker returns best-first dicts with kind, id, canvas,
# canvas_title, snippet and key. Nothing else changes.


def _item(conn: sqlite3.Connection, h: dict, score: float, matched_by: list[str]) -> dict:
    if h["kind"] == "chunk":
        chunk_id = h["id"]
        rec = conn.execute(_BEST_RECOGNITION, (h["id"], h.get("content_hash"))).fetchone()
        source = rec["source"] if rec else None
    else:
        chunk_id = next(
            (
                s.get("id")
                for s in json.loads(h.get("sources_json") or "[]")
                if s.get("type") == "chunk"
            ),
            None,
        )
        source = "answer"
    return {
        "kind": h["kind"],
        "id": h["id"],
        "chunk_id": chunk_id,
        "canvas": h["canvas"],
        "canvas_title": h["canvas_title"],
        "snippet": h.get("snippet", ""),
        "source": source,
        "score": score,
        "matched_by": matched_by,
    }


def retrieve(
    conn: sqlite3.Connection,
    query: str,
    scope: str = "canvas",
    document_id: str = "default",
    k: int = 8,
) -> list[dict]:
    """Best-first hits from every ranker, fused by rank. The API adds `deep_link`."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    doc = document_id if scope == "canvas" else None
    lists: dict[str, list[Key]] = {}
    detail: dict[Key, dict] = {}
    for name, ranker in RANKERS.items():
        hits = ranker(conn, query, doc, CANDIDATES)
        lists[name] = [h["key"] for h in hits]
        for h in hits:
            detail.setdefault(h["key"], h)
    return [
        _item(conn, detail[key], round(score, 6), matched_by)
        for key, score, matched_by in rrf(lists)[:k]
    ]
