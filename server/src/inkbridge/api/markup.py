"""Mark-up crop routes (INK-141, decision 0102): the diagram and the ink drawn over it. Read-only."""

from fastapi import APIRouter, HTTPException, Response

from inkbridge.agent import markup
from inkbridge.api.deps import Conn
from inkbridge.db import diagrams as diagrams_db

router = APIRouter()


def _diagram(conn, document_id: str, diagram_id: str) -> dict:
    d = diagrams_db.get(conn, diagram_id)
    if d is None or d["document_id"] != document_id:
        raise HTTPException(404, "diagram not found")
    return d


@router.get("/documents/{document_id}/diagrams/{diagram_id}/markup")
def get_markup(document_id: str, diagram_id: str, conn: Conn) -> dict:
    d = _diagram(conn, document_id, diagram_id)
    ink = markup.ink_over(conn, d, window_s=None)
    box = markup._box(markup.diagram_elements(conn, d) + [e for _, e in ink])
    return {
        "diagram_id": d["id"],
        "version": d["version"],
        "source": d["source"],
        "source_kind": d["source_kind"],
        "ink_ids": [e["id"] for _, e in ink],
        "box": [] if box is None else [box[0], box[1], box[2] - box[0], box[3] - box[1]],
    }


@router.get("/documents/{document_id}/diagrams/{diagram_id}/markup.png")
def get_markup_png(document_id: str, diagram_id: str, conn: Conn) -> Response:
    png = markup.render(conn, _diagram(conn, document_id, diagram_id))
    if png is None:
        raise HTTPException(404, "nothing to draw")
    return Response(png, media_type="image/png")
