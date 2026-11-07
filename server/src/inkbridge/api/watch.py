"""Watch route (INK-132, decision 0091): the export skill registers chunk ids and reading hashes.

Strict on purpose: this is where the "backend stores no note text" invariant is enforced.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from inkbridge import db
from inkbridge.api.deps import Conn

router = APIRouter()

ID = r"^[A-Za-z0-9_:-]{1,64}$"
HASH = r"^[0-9a-f]{16,64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WatchChunk(_Strict):
    id: str = Field(pattern=ID)
    reading_hash: str = Field(
        pattern=HASH
    )  # text_hash of the chunk reading the note was written from


class WatchIn(_Strict):
    note: str = Field(pattern=ID)  # opaque id the skill derives; never a path or title
    chunks: list[WatchChunk] = Field(max_length=500)


@router.post("/documents/{document_id}/watch")
def watch(document_id: str, body: WatchIn, conn: Conn) -> dict:
    try:
        n = db.put_watch(
            conn, document_id, body.note, [(c.id, c.reading_hash) for c in body.chunks]
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    return {"note": body.note, "chunks": n}
