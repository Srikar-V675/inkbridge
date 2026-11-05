"""Read-only chunk graph over arrow links, built per request (INK-060, decision 0056)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from inkbridge import db
from inkbridge.api.chunks import NOT_FOUND, Out, deep_link
from inkbridge.api.deps import Conn
from inkbridge.canvas import graph
from inkbridge.db import outline

router = APIRouter()

Direction = Literal["both", "out", "in"]


class GraphOut(Out):
    document: str
    version: int


def _load(conn, document_id: str) -> dict:
    try:
        return outline.chunk_outline(conn, document_id, status="all")
    except db.DocumentNotFound:
        raise HTTPException(404, NOT_FOUND) from None


def _resolve(chunks: list[dict], chunk_id: str) -> tuple[str, str | None]:
    """Active id to use, and a note when it differs. 404 unknown, 410 orphan dead end."""
    by_id = {c["id"]: c for c in chunks}
    cur, seen = by_id.get(chunk_id), {chunk_id}
    if cur is None:
        raise HTTPException(
            404,
            {
                "code": "chunk_not_found",
                "msg": f"chunk {chunk_id} is not on this canvas; read_canvas lists chunk ids",
            },
        )
    while cur["status"] != "active":
        nxt = by_id.get(cur.get("successor_of") or "")
        if nxt is None or nxt["id"] in seen:
            raise HTTPException(
                410,
                {
                    "code": "chunk_gone",
                    "msg": f"chunk {chunk_id} was replaced or deleted and has no live "
                    "successor; call read_canvas",
                },
            )
        seen.add(nxt["id"])
        cur = nxt
    note = None if cur["id"] == chunk_id else f"chunk {chunk_id} was replaced; showing {cur['id']}"
    return cur["id"], note


def _link_nodes(document_id: str, result: dict) -> None:
    for n in result["nodes"]:
        n["deep_link"] = deep_link(document_id, n["id"])


@router.get("/documents/{document_id}/graph/subgraph", response_model=GraphOut)
def get_subgraph(
    document_id: str,
    conn: Conn,
    chunk_id: str,
    depth: Annotated[int, Query(ge=1, le=5)] = 1,
    direction: Direction = "both",
    max_nodes: Annotated[int, Query(ge=1, le=100)] = 40,
    max_edges: Annotated[int, Query(ge=1, le=200)] = 80,
    mermaid: bool = False,
) -> dict:
    """Chunks within `depth` arrow hops of chunk_id (an orphaned id is followed to its successor)."""
    data = _load(conn, document_id)
    center, note = _resolve(data["chunks"], chunk_id)
    g = graph.build(data["chunks"])
    result = graph.subgraph(g, center, depth, direction, max_nodes, max_edges)
    _link_nodes(document_id, result)
    out = {
        "document": document_id,
        "version": data["version"],
        "anchor_used": center if note else None,
        "note": note,
        **result,
    }
    if mermaid:
        out["mermaid"] = graph.mermaid(result["nodes"], result["edges"])
    return out


@router.get("/documents/{document_id}/graph/path", response_model=GraphOut)
def get_path(
    document_id: str,
    conn: Conn,
    from_chunk: str,
    to_chunk: str,
    direction: Direction = "both",
    mermaid: bool = False,
) -> dict:
    """Shortest arrow path between two chunks."""
    data = _load(conn, document_id)
    src, src_note = _resolve(data["chunks"], from_chunk)
    dst, dst_note = _resolve(data["chunks"], to_chunk)
    g = graph.build(data["chunks"])
    result = graph.path(g, src, dst, direction)
    _link_nodes(document_id, result)
    notes = [n for n in (src_note, dst_note) if n]
    out = {
        "document": document_id,
        "version": data["version"],
        "anchor_used": {"from": src, "to": dst} if notes else None,
        "note": "; ".join(notes) or None,
        **result,
    }
    if mermaid:
        out["mermaid"] = graph.mermaid(result["nodes"], result["edges"])
    return out


@router.get("/documents/{document_id}/graph/components", response_model=GraphOut)
def get_components(document_id: str, conn: Conn) -> dict:
    """Groups of chunks joined by arrows, largest first, and how many chunks stand alone."""
    data = _load(conn, document_id)
    return {
        "document": document_id,
        "version": data["version"],
        **graph.components(graph.build(data["chunks"])),
    }
