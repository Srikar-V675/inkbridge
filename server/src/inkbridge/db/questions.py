"""Questions the user asks on a canvas (INK-047, pull path).

The backend only stores the question and the answer an agent hands back. Nothing here starts a
process or calls a model, so a row leaves `pending` only through answer or cancel.
Lifecycle: pending -> answered | cancelled.
"""

import json
import sqlite3
import uuid

from inkbridge.db.common import AUTO, DocumentNotFound, _now
from inkbridge.db.documents import document_exists

HISTORY_MAX = 5  # earlier question/answer pairs of a thread sent along with a question
STATUSES = ("pending", "answered", "cancelled")


class QuestionNotFound(Exception):
    pass


class ParentNotFound(Exception):
    pass


class InvalidTransition(Exception):
    def __init__(self, current: str):
        super().__init__(current)
        self.current = current


def create_question(
    conn: sqlite3.Connection,
    document_id: str,
    text: str,
    focus_element_ids: list[str],
    parent_id: str | None,
) -> dict:
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    if (
        parent_id is not None
        and not conn.execute(
            "SELECT 1 FROM questions WHERE id = ? AND document_id = ?", (parent_id, document_id)
        ).fetchone()
    ):
        raise ParentNotFound(parent_id)
    qid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO questions (id, document_id, parent_id, text, focus_element_ids, status,"
        " created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (
            qid,
            document_id,
            parent_id,
            text,
            json.dumps(list(dict.fromkeys(focus_element_ids))),
            _now(),
        ),
    )
    conn.commit()
    return get_question(conn, qid)


def get_question(conn: sqlite3.Connection, question_id: str) -> dict:
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise QuestionNotFound(question_id)
    return _full(conn, row, _chunk_map(conn, row["document_id"]))


def list_questions(
    conn: sqlite3.Connection, document_id: str, status: str | None, limit: int
) -> list[dict]:
    """Oldest first: an answering agent works the queue in order."""
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    sql, args = "SELECT * FROM questions WHERE document_id = ?", [document_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY created_at, rowid LIMIT ?"
    args.append(limit)
    chunk_map = _chunk_map(conn, document_id)  # once per call, not per question
    return [_full(conn, r, chunk_map) for r in conn.execute(sql, args).fetchall()]


def answer_question(
    conn: sqlite3.Connection, question_id: str, answer_md: str, sources: list[dict]
) -> dict:
    # The status guard is in the UPDATE itself, so two racing answers cannot both win.
    cur = conn.execute(
        "UPDATE questions SET status = 'answered', answer_md = ?, sources_json = ?"
        " WHERE id = ? AND status = 'pending'",
        (answer_md, json.dumps(sources), question_id),
    )
    return _finish(conn, question_id, cur.rowcount)


def cancel_question(conn: sqlite3.Connection, question_id: str) -> dict:
    cur = conn.execute(
        "UPDATE questions SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
        (question_id,),
    )
    return _finish(conn, question_id, cur.rowcount)


def _finish(conn: sqlite3.Connection, question_id: str, changed: int) -> dict:
    if not changed:
        row = conn.execute("SELECT status FROM questions WHERE id = ?", (question_id,)).fetchone()
        if row is None:
            raise QuestionNotFound(question_id)
        raise InvalidTransition(row["status"])
    conn.commit()
    return get_question(conn, question_id)


def _chunk_map(conn: sqlite3.Connection, document_id: str) -> list[tuple[str, set[str]]]:
    rows = conn.execute(
        "SELECT id, element_ids_json FROM regions WHERE document_id = ? AND created_by = ?"
        " AND status = 'active' ORDER BY id",
        (document_id, AUTO),
    )
    return [(r["id"], set(json.loads(r["element_ids_json"]))) for r in rows]


def _full(conn: sqlite3.Connection, row: sqlite3.Row, chunks: list[tuple[str, set[str]]]) -> dict:
    focus = json.loads(row["focus_element_ids"])
    wanted = set(focus)
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "parent_id": row["parent_id"],
        "text": row["text"],
        "focus_element_ids": focus,
        # Computed now, not stored: chunk ids change when chunks split or merge.
        "focus_chunk_ids": [cid for cid, ids in chunks if ids & wanted],
        "status": row["status"],
        "answer_md": row["answer_md"],
        "sources": json.loads(row["sources_json"]) if row["sources_json"] else [],
        "history": _history(conn, row),
        "created_at": row["created_at"],
    }


def _history(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict]:
    """Ancestors via parent_id, oldest first, at most HISTORY_MAX; built from rows only."""
    out, seen, parent = [], {row["id"]}, row["parent_id"]
    while parent and parent not in seen and len(out) < HISTORY_MAX:
        seen.add(parent)
        p = conn.execute("SELECT * FROM questions WHERE id = ?", (parent,)).fetchone()
        if p is None:
            break
        out.append(
            {"id": p["id"], "text": p["text"], "answer_md": p["answer_md"], "status": p["status"]}
        )
        parent = p["parent_id"]
    return out[::-1]
