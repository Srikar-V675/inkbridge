"""Manual chunk merge and split (INK-059). Overrides are server state; the scene is never written."""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from inkbridge import db
from inkbridge.api.deps import Conn

router = APIRouter()

MAX_MERGE = 100
MAX_SPLIT_ELEMENTS = 50_000

Id = Annotated[str, Field(min_length=1, max_length=200)]


class MergeIn(BaseModel):
    chunk_ids: list[Id] = Field(max_length=MAX_MERGE)


class SplitIn(BaseModel):
    chunk_id: Id
    element_ids: list[Id] = Field(max_length=MAX_SPLIT_ELEMENTS)


def _run(fn, *args):
    try:
        return fn(*args)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.ChunkNotFound as e:
        raise HTTPException(
            404, f"chunk {e} not found on this canvas; list its chunks again"
        ) from None
    except db.ChunkNotActive as e:
        raise HTTPException(
            409, f"chunk {e} is orphaned (already replaced); reload the chunk list"
        ) from None
    except db.InvalidOverride as e:
        raise HTTPException(422, str(e)) from None


@router.post("/documents/{document_id}/chunks/merge")
def merge_chunks(document_id: str, body: MergeIn, conn: Conn) -> dict:
    chunk, orphaned = _run(db.merge_chunks, conn, document_id, body.chunk_ids)
    return {"chunk": chunk, "orphaned": orphaned}


@router.post("/documents/{document_id}/chunks/split")
def split_chunk(document_id: str, body: SplitIn, conn: Conn) -> dict:
    chunks, orphaned = _run(
        db.split_chunk, conn, document_id, body.chunk_id, sorted(set(body.element_ids))
    )
    return {"chunks": chunks, "orphaned": orphaned}
