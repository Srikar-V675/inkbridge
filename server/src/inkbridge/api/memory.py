"""Canvas brief and what-changed routes (INK-135, decision 0093). Neither touches scene elements."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from inkbridge import db
from inkbridge.api.deps import Conn

router = APIRouter()


class BriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(max_length=db.MAX_BRIEF_CHARS)


@router.get("/documents/{document_id}/brief")
def get_brief(document_id: str, conn: Conn) -> dict:
    try:
        return db.get_memory(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None


@router.put("/documents/{document_id}/brief")
def put_brief(document_id: str, body: BriefIn, conn: Conn) -> dict:
    try:
        return db.set_brief(conn, document_id, body.brief)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None


@router.get("/documents/{document_id}/changes")
def changes(
    document_id: str,
    conn: Conn,
    since: Annotated[int | None, Query(ge=0)] = None,
    mark_seen: bool = False,
) -> dict:
    """Chunks changed since `since` (default: the saved cursor).

    With mark_seen=true this GET moves the cursor: it only touches the agent's own bookmark.
    """
    try:
        return db.what_changed(conn, document_id, since, mark_seen)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
