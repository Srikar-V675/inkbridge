"""Agent task routes (INK-133, decision 0095): list, claim, complete. The pull path and the runner
share these rows; the op limit is enforced in api/ops.py."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from inkbridge import db
from inkbridge.agent.activity import activity
from inkbridge.api.deps import Conn
from inkbridge.api.ws import hub
from inkbridge.db import questions as q_db
from inkbridge.db import tasks as tasks_db

router = APIRouter()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimIn(_Strict):
    claimed_by: str = Field(min_length=1, max_length=64)


class CompleteIn(_Strict):
    status: Literal["done", "failed"]
    error: str | None = Field(default=None, max_length=2_000)


def publish(task: dict) -> dict:
    hub.publish(task["document_id"], tasks_db.ws_message(task))
    activity.on_task(task)  # the working dot (INK-198); after the task line, which tabs read first
    return task


def _with_question(conn, task: dict) -> dict:
    if task["question_id"]:
        task = {**task, "question": q_db.get_question(conn, task["question_id"])}
    return task


def _changed(fn, conn, task_id: str, *args) -> dict:
    try:
        task = fn(conn, task_id, *args)
    except tasks_db.TaskNotFound:
        raise HTTPException(404, "task not found") from None
    except tasks_db.InvalidTransition as e:
        raise HTTPException(409, {"code": "invalid_transition", "status": e.current}) from None
    return publish(_with_question(conn, task))


@router.get("/documents/{document_id}/tasks")
def list_tasks(
    document_id: str,
    conn: Conn,
    status: Annotated[
        Literal["pending", "running", "done", "failed", "cancelled"] | None, Query()
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    if not db.document_exists(conn, document_id):
        raise HTTPException(404, "document not found")
    rows = tasks_db.list_tasks(conn, document_id, status, limit)
    return {"tasks": [_with_question(conn, t) for t in rows]}


@router.post("/tasks/{task_id}/claim")
def claim(task_id: str, body: ClaimIn, conn: Conn) -> dict:
    return _changed(tasks_db.claim, conn, task_id, body.claimed_by)


@router.post("/tasks/{task_id}/complete")
def complete(task_id: str, body: CompleteIn, conn: Conn) -> dict:
    try:
        t = tasks_db.get_task(conn, task_id)
    except tasks_db.TaskNotFound:
        raise HTTPException(404, "task not found") from None
    if (
        body.status == "done"
        and t["question_id"]
        and q_db.get_question(conn, t["question_id"])["status"] == "pending"
    ):
        raise HTTPException(
            409, {"code": "question_unanswered", "msg": "answer the question first"}
        )
    return _changed(tasks_db.finish, conn, task_id, body.status, body.error)
