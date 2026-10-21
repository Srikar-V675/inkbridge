from typing import Annotated

from fastapi import APIRouter, Query

from inkbridge import db
from inkbridge.api.deps import Conn

router = APIRouter()


@router.get("/search")
def search(
    conn: Conn,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    document_id: str | None = None,
) -> list[dict]:
    return db.search(conn, q, limit=limit, document_id=document_id)
