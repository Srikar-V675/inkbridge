"""Agent write queue routes (INK-041). MCP tools enqueue; the browser acks; the user resolves."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkbridge import db
from inkbridge.api.deps import Conn
from inkbridge.db import ops as ops_db

router = APIRouter()

OpType = Literal["write_text", "draw_diagram"]
OpId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ElementId = Annotated[str, Field(min_length=1, max_length=256)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteTextPayload(_Strict):
    text: str = Field(min_length=1, max_length=10_000)
    anchor: str | None = None  # chunk (region) id to place beside


class DrawDiagramPayload(_Strict):
    mermaid: str = Field(min_length=1, max_length=20_000)  # flowchart only
    anchor: str | None = None


_PAYLOADS: dict[str, type[_Strict]] = {
    "write_text": WriteTextPayload,
    "draw_diagram": DrawDiagramPayload,
}


class OpIn(_Strict):
    type: OpType  # no edit or delete type exists, so none can be expressed
    payload: dict[str, Any]  # checked for existing ids first, then against its type's schema
    op_id: OpId | None = None  # client-chosen id makes a retried POST idempotent


class OpInWithDocument(OpIn):
    document_id: str = db.DEFAULT_DOCUMENT_ID


class OpPatch(_Strict):
    status: Literal["applied", "failed", "expired", "accepted", "rejected"]
    element_ids: list[ElementId] | None = Field(default=None, max_length=10_000)
    error: str | None = Field(default=None, max_length=2_000)


def _existing(ids: list[str]) -> HTTPException:
    return HTTPException(422, {"code": "existing_element_id", "ids": ids})


def _enqueue(conn, document_id: str, body: OpIn, response: Response) -> dict:
    try:
        # Before the schema: an existing id must be refused whichever field carries it.
        ops_db.check_payload(conn, document_id, body.payload)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except ops_db.ExistingElementIds as e:
        raise _existing(e.ids) from None
    try:
        payload = _PAYLOADS[body.type].model_validate(body.payload)
    except ValidationError as e:
        errors = [{"loc": ["payload", *e_["loc"]], "msg": e_["msg"]} for e_ in e.errors()]
        raise HTTPException(422, errors) from None
    try:
        op, created = ops_db.create_op(
            conn, document_id, body.type, payload.model_dump(exclude_none=True), body.op_id
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except ops_db.ExistingElementIds as e:
        raise _existing(e.ids) from None
    except ops_db.AnchorNotFound:
        raise HTTPException(422, {"code": "anchor_not_found", "anchor": payload.anchor}) from None
    except ops_db.OpConflict:
        raise HTTPException(409, {"code": "op_id_conflict", "op_id": body.op_id}) from None
    response.status_code = 201 if created else 200
    return op


@router.post("/documents/{document_id}/ops", status_code=201)
def create_op(document_id: str, body: OpIn, conn: Conn, response: Response) -> dict:
    return _enqueue(conn, document_id, body, response)


@router.post("/ops", status_code=201)
def create_op_default(body: OpInWithDocument, conn: Conn, response: Response) -> dict:
    return _enqueue(conn, body.document_id, body, response)


@router.get("/documents/{document_id}/ops")
def list_ops(
    document_id: str,
    conn: Conn,
    status: Annotated[str | None, Query(description="comma-separated statuses")] = None,
) -> dict:
    statuses = [s for s in (status or "").split(",") if s]
    bad = [s for s in statuses if s not in ops_db.STATUSES]
    if bad:
        raise HTTPException(422, f"unknown status: {', '.join(bad)}")
    if not db.document_exists(conn, document_id):
        raise HTTPException(404, "document not found")
    return {"ops": ops_db.list_ops(conn, document_id, statuses)}


@router.get("/ops/{op_id}")
def get_op(op_id: str, conn: Conn) -> dict:
    try:
        return ops_db.get_op(conn, op_id)
    except ops_db.OpNotFound:
        raise HTTPException(404, "op not found") from None


@router.patch("/ops/{op_id}")
def patch_op(op_id: str, body: OpPatch, conn: Conn) -> dict:
    """Browser: applied (with the new element ids) or failed. User: accepted or rejected."""
    if body.status == "applied" and not body.element_ids:
        raise HTTPException(422, "applied needs the element_ids the browser created")
    ids = list(dict.fromkeys(body.element_ids or []))
    error = body.error or ("unknown error" if body.status == "failed" else None)
    try:
        return ops_db.update_status(conn, op_id, body.status, ids or None, error)
    except ops_db.OpNotFound:
        raise HTTPException(404, "op not found") from None
    except ops_db.ExistingElementIds as e:
        raise _existing(e.ids) from None
    except ops_db.InvalidTransition as e:
        raise HTTPException(
            409, {"code": "invalid_transition", "status": e.current, "wanted": body.status}
        ) from None
