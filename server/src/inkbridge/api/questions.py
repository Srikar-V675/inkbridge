"""Questions routes (INK-047). The user asks; any MCP client answers via list/answer_question."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkbridge import db
from inkbridge.api.chunks import Out
from inkbridge.api.deps import Conn
from inkbridge.api.ws import hub
from inkbridge.db import questions as q_db

router = APIRouter()

ElementId = Annotated[str, Field(min_length=1, max_length=256)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    """What an answer rests on: a chunk on the canvas or a note in the vault."""

    type: Literal["chunk", "note"]
    id: str | None = Field(default=None, min_length=1, max_length=256)
    path: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _shape(self) -> "Source":
        if self.type == "chunk" and (self.id is None or self.path is not None):
            raise ValueError("a chunk source needs id and no path")
        if self.type == "note" and (self.path is None or self.id is not None):
            raise ValueError("a note source needs path and no id")
        return self


class QuestionIn(_Strict):
    text: str = Field(min_length=1, max_length=4_000)
    focus_element_ids: list[ElementId] = Field(default_factory=list, max_length=200)
    parent_id: str | None = Field(default=None, max_length=64)


class AnswerIn(_Strict):
    answer_md: str = Field(min_length=1, max_length=20_000)  # untrusted markdown, stored as is
    sources: list[Source] = Field(default_factory=list, max_length=50)
    canvas_text: str | None = Field(default=None, min_length=1, max_length=600)
    document_id: str | None = Field(default=None, max_length=256)  # INK-191: refuse a wrong canvas
    final: bool = True  # false: answer_md is a streamed piece appended to the partial (INK-176)


class HistoryItem(Out):
    id: str
    text: str
    answer_md: str | None
    status: str


class QuestionOut(Out):
    id: str
    document_id: str
    parent_id: str | None
    text: str
    focus_element_ids: list[str]
    focus_chunk_ids: list[str]
    status: str
    answer_md: str | None
    canvas_text: str | None
    sources: list[dict]
    history: list[HistoryItem]
    runner_status: str
    runner_error: str | None
    partial_answer: str | None
    partial_seq: int
    created_at: str


class QuestionList(Out):
    questions: list[QuestionOut]


def _publish(q: dict) -> dict:
    hub.publish(q["document_id"], {"type": "question.update", "question": q})
    return q


def _transition(fn, conn, question_id, *args) -> dict:
    try:
        return _publish(fn(conn, question_id, *args))
    except q_db.QuestionNotFound:
        raise HTTPException(404, f"question {question_id} not found") from None
    except q_db.InvalidTransition as e:
        raise HTTPException(409, {"code": "invalid_transition", "status": e.current}) from None


@router.post("/documents/{document_id}/questions", status_code=201, response_model=QuestionOut)
def create_question(document_id: str, body: QuestionIn, conn: Conn, request: Request) -> dict:
    try:
        q = q_db.create_question(
            conn, document_id, body.text, body.focus_element_ids, body.parent_id
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except q_db.ParentNotFound:
        raise HTTPException(
            422, {"code": "parent_not_found", "msg": "parent_id is not a question on this canvas"}
        ) from None
    if err := getattr(request.app.state, "runner_error", None):
        q = q_db.set_runner(conn, q["id"], "failed", err)
    return _publish(q)


@router.get("/documents/{document_id}/questions", response_model=QuestionList)
def list_questions(
    document_id: str,
    conn: Conn,
    status: Literal["pending", "answered", "cancelled"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    try:
        return {"questions": q_db.list_questions(conn, document_id, status, limit)}
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None


@router.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(question_id: str, conn: Conn) -> dict:
    try:
        return q_db.get_question(conn, question_id)
    except q_db.QuestionNotFound:
        raise HTTPException(404, f"question {question_id} not found") from None


@router.post("/questions/{question_id}/answer", response_model=QuestionOut)
def answer_question(question_id: str, body: AnswerIn, conn: Conn) -> dict:
    if body.document_id is not None:
        try:
            owner = q_db.get_question(conn, question_id)["document_id"]
        except q_db.QuestionNotFound:
            raise HTTPException(
                404, f"question {question_id} not found on canvas {body.document_id!r}"
            ) from None
        if owner != body.document_id:
            raise HTTPException(
                409,
                {
                    "code": "question_other_canvas",
                    "msg": f"question {question_id} belongs to canvas {owner!r}, not "
                    f"{body.document_id!r}; call list_questions with document_id={owner!r}",
                },
            )
    if not body.final:
        try:
            seq = q_db.append_partial(conn, question_id, body.answer_md)
        except q_db.QuestionNotFound:
            raise HTTPException(404, f"question {question_id} not found") from None
        except q_db.InvalidTransition as e:
            raise HTTPException(409, {"code": "invalid_transition", "status": e.current}) from None
        except q_db.PartialTooLong:
            raise HTTPException(422, {"code": "partial_too_long"}) from None
        q = q_db.get_question(conn, question_id)
        hub.publish(
            q["document_id"],
            {"type": "question.delta", "id": question_id, "seq": seq, "text": body.answer_md},
        )
        return q
    sources = [s.model_dump(exclude_none=True) for s in body.sources]
    return _transition(
        q_db.answer_question, conn, question_id, body.answer_md, sources, body.canvas_text
    )


@router.post("/questions/{question_id}/cancel", response_model=QuestionOut)
def cancel_question(question_id: str, conn: Conn) -> dict:
    return _transition(q_db.cancel_question, conn, question_id)
