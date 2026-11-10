"""Agent tasks (INK-133, decision 0095): one queue for questions and tapped offers. Pure sqlite.

A task has a `kind` (what created it) and a mode in `input_json["mode"]` (what it may do). The
op limit lives here and the API enforces it; the MCP client and the runner prompt are not trusted.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from inkbridge.db.common import _now

CLAIM_TTL_S = 15 * 60  # a client that claimed and went silent loses the task (hypothesis)

MODES = {
    "question": {"types": ("write_text", "draw_diagram"), "limit": 3},
    "diagram": {"types": ("draw_diagram",), "limit": 2},
    "markup": {"types": ("draw_diagram",), "limit": 1},
    "link": {"types": (), "limit": 0},
    "brief": {"types": (), "limit": 0},
}
OFFER_MODE = {"sketch": "diagram", "markup": "markup", "dangling_arrow": "link", "related": "link"}


class TaskNotFound(Exception):
    pass


class InvalidTransition(Exception):
    def __init__(self, current: str):
        super().__init__(current)
        self.current = current


class TaskRefused(Exception):
    def __init__(self, code: str, msg: str):
        super().__init__(code)
        self.code, self.msg = code, msg


def _dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    d["mode"] = d["input"].get("mode", "question")
    mode = MODES[d["mode"]]
    d["allowed_op_types"] = list(mode["types"])
    d["op_limit"] = mode["limit"]
    return d


def create_task(
    conn: sqlite3.Connection,
    document_id: str,
    kind: str,
    *,
    question_id: str | None = None,
    offer_id: str | None = None,
    input: dict | None = None,
) -> dict:
    """No commit: the caller owns the transaction."""
    tid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO agent_tasks (id, document_id, kind, question_id, offer_id, input_json,"
        " created_at) VALUES (?,?,?,?,?,?,?)",
        (tid, document_id, kind, question_id, offer_id, json.dumps(input or {}), _now()),
    )
    return get_task(conn, tid)


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise TaskNotFound(task_id)
    return _dict(row)


def task_for_question(conn: sqlite3.Connection, question_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM agent_tasks WHERE question_id = ?", (question_id,)).fetchone()
    return _dict(row) if row else None


def expire_claims(conn: sqlite3.Connection) -> None:
    """Running tasks claimed longer ago than CLAIM_TTL_S go back to pending."""
    cutoff = (datetime.now(UTC) - timedelta(seconds=CLAIM_TTL_S)).isoformat()
    conn.execute(
        "UPDATE agent_tasks SET status='pending', last_error='claim expired'"
        " WHERE status='running' AND claimed_at < ?",
        (cutoff,),
    )
    conn.commit()


def list_tasks(
    conn: sqlite3.Connection, document_id: str, status: str | None, limit: int
) -> list[dict]:
    """Oldest first, question tasks before the rest."""
    expire_claims(conn)
    sql, args = "SELECT * FROM agent_tasks WHERE document_id = ?", [document_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY kind != 'question', created_at, rowid LIMIT ?"
    args.append(limit)
    return [_dict(r) for r in conn.execute(sql, args)]


def _guard(conn: sqlite3.Connection, cur: sqlite3.Cursor, task_id: str) -> None:
    if cur.rowcount:
        return
    row = conn.execute("SELECT status FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise TaskNotFound(task_id)
    raise InvalidTransition(row["status"])


def claim(conn: sqlite3.Connection, task_id: str, claimed_by: str) -> dict:
    expire_claims(conn)
    cur = conn.execute(
        "UPDATE agent_tasks SET status='running', claimed_by=?, claimed_at=?, attempts=attempts+1"
        " WHERE id=? AND status='pending'",
        (claimed_by, _now(), task_id),
    )
    _guard(conn, cur, task_id)
    conn.commit()
    return get_task(conn, task_id)


def finish(conn: sqlite3.Connection, task_id: str, status: str, error: str | None = None) -> dict:
    assert status in ("done", "failed")
    cur = conn.execute(
        "UPDATE agent_tasks SET status=?, last_error=?, finished_at=? WHERE id=? AND status='running'",
        (status, error[:200] if error else None, _now(), task_id),
    )
    _guard(conn, cur, task_id)
    conn.commit()
    return get_task(conn, task_id)


def release(conn: sqlite3.Connection, task_id: str, error: str, give_up: bool = False) -> dict:
    """Runner failure: back to pending, or failed when the worker gives up (it counts the tries)."""
    cur = conn.execute(
        "UPDATE agent_tasks SET status = ?, last_error=?, finished_at = ?"
        " WHERE id=? AND status='running'",
        ("failed" if give_up else "pending", error[:200], _now() if give_up else None, task_id),
    )
    _guard(conn, cur, task_id)
    conn.commit()
    return get_task(conn, task_id)


def finish_for_question(conn: sqlite3.Connection, question_id: str, status: str) -> None:
    """Inside the question's transaction; no commit."""
    conn.execute(
        "UPDATE agent_tasks SET status=?, finished_at=? WHERE question_id=?"
        " AND status IN ('pending','running')",
        (status, _now(), question_id),
    )


def runner_count_today(conn: sqlite3.Connection) -> int:
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) FROM agent_tasks WHERE claimed_by='runner' AND kind != 'question'"
        " AND claimed_at >= ?",
        (since,),
    ).fetchone()[0]


def reset_runner(conn: sqlite3.Connection) -> None:
    """At API start: a task the runner was working on goes back to pending."""
    conn.execute(
        "UPDATE agent_tasks SET status='pending' WHERE status='running' AND claimed_by='runner'"
    )
    conn.commit()


def status_message(task: dict) -> str:
    s = task["status"]
    if s == "running":
        return "Working on it"
    if s == "done":
        return "Done"
    if s == "failed":
        return f"Failed: {task['last_error']}" if task.get("last_error") else "Failed"
    return "Waiting" if s == "pending" else "Cancelled"


def ws_message(task: dict) -> dict:
    return {
        "type": "task.status",
        "task_id": task["id"],
        "kind": task["kind"],
        "status": task["status"],
        "line": status_message(task),
    }


def op_budget(conn: sqlite3.Connection, task_id: str, document_id: str, op_type: str) -> None:
    t = get_task(conn, task_id)  # TaskNotFound -> 404 in the API
    if t["document_id"] != document_id:
        raise TaskRefused(
            "task_other_canvas",
            f"task {task_id} belongs to canvas {t['document_id']!r}, not {document_id!r}; "
            "pass the task's document_id to the tool",
        )
    if t["status"] != "running":
        raise TaskRefused("task_not_running", f"task is {t['status']}; claim it first")
    if op_type not in t["allowed_op_types"]:
        raise TaskRefused("task_mode", f"{op_type} is not allowed in this task's mode")
    used = conn.execute("SELECT COUNT(*) FROM agent_ops WHERE task_id = ?", (task_id,)).fetchone()[
        0
    ]
    if used >= t["op_limit"]:
        raise TaskRefused(
            "task_op_limit", f"this task already made {used} of {t['op_limit']} drafts"
        )
