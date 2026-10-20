import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from inkbridge import db
from inkbridge.api import regions, search
from inkbridge.api.deps import Conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Inkbridge", lifespan=lifespan)
app.include_router(regions.router)
app.include_router(search.router)


class SceneIn(BaseModel):
    base_version: int = Field(ge=0)
    elements: list[dict[str, Any]]

    @field_validator("elements")
    @classmethod
    def _elements_have_ids(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not all(isinstance(e.get("id"), str) for e in v):
            raise ValueError("every element needs a string id")
        return v


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/documents/{document_id}/scene")
def get_scene(document_id: str, conn: Conn) -> dict[str, Any]:
    try:
        version, elements_json = db.get_scene(conn, document_id)
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    return {"version": version, "elements": json.loads(elements_json)}


@app.put("/documents/{document_id}/scene")
def put_scene(document_id: str, body: SceneIn, conn: Conn) -> dict[str, int]:
    try:
        version = db.put_scene(
            conn,
            document_id,
            body.base_version,
            json.dumps(body.elements, ensure_ascii=False, separators=(",", ":")),
        )
    except db.DocumentNotFound:
        raise HTTPException(404, "document not found") from None
    except db.VersionConflict as e:
        raise HTTPException(409, {"current_version": e.current_version}) from None
    return {"version": version}
