"""GET /retrieve: related ink and past answers, on one canvas or across canvases (INK-136)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from inkbridge import db
from inkbridge.api.chunks import NOT_FOUND, Out, deep_link
from inkbridge.api.deps import Conn
from inkbridge.db import retrieve as retrieve_db

router = APIRouter()


class RetrieveHit(Out):
    kind: str
    id: str
    chunk_id: str | None
    canvas: str
    canvas_title: str
    snippet: str
    deep_link: str
    source: str | None
    score: float
    matched_by: list[str]


class RetrieveOut(Out):
    results: list[RetrieveHit]


@router.get("/retrieve", response_model=RetrieveOut)
def retrieve(
    conn: Conn,
    q: Annotated[str, Query(min_length=1)],
    scope: Literal["canvas", "all"] = "canvas",
    document_id: str = db.DEFAULT_DOCUMENT_ID,
    k: Annotated[int, Query(ge=1, le=50)] = 8,
) -> dict:
    if scope == "canvas" and not db.document_exists(conn, document_id):
        raise HTTPException(404, NOT_FOUND)
    hits = retrieve_db.retrieve(conn, q, scope, document_id, k)
    for h in hits:
        h["deep_link"] = deep_link(h["canvas"], h["chunk_id"])
    return {"results": hits}
