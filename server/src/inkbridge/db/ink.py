"""Reads of raw ink for agents: links, a region's strokes, sketch elements."""

import json
import logging
import sqlite3

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.documents import get_scene
from inkbridge.db.regions import get_region


def list_links(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Links between the document's current chunks, as {from, to, kind}."""
    return [
        {"from": r["from_region"], "to": r["to_region"], "kind": r["kind"]}
        for r in conn.execute(
            "SELECT DISTINCT from_region, to_region, kind FROM links WHERE document_id = ?"
            " ORDER BY from_region, to_region, kind",
            (document_id,),
        )
    ]


def get_region_ink(conn: sqlite3.Connection, region_id: str) -> dict | None:
    """Raw stroke points/pressures of a region's live elements, from the current scene."""
    region = get_region(conn, region_id)
    if region is None:
        return None
    _, elements_json = get_scene(conn, region["document_id"])
    by_id = {e["id"]: e for e in json.loads(elements_json)}
    strokes = [
        {
            "id": i,
            "x": by_id[i].get("x", 0),
            "y": by_id[i].get("y", 0),
            "angle": by_id[i].get("angle", 0),
            "points": by_id[i].get("points", []),
            "pressures": by_id[i].get("pressures", []),
        }
        for i in region["element_ids"]
        if i in by_id and not by_id[i].get("isDeleted")
    ]
    return {"strokes": strokes, "point_count": sum(len(s["points"]) for s in strokes)}


def get_sketch_elements(
    conn: sqlite3.Connection, region_id: str, by_id: dict[str, dict] | None = None
) -> list[dict] | None:
    """Live, non-draft elements of a region plus those of regions an arrow links it to (one hop).

    A sketched flowchart with long arrows splits into one chunk per node joined by `links`, so
    reading one chunk alone would leave every arrow without a target. None if the region is unknown.
    """
    region = get_region(conn, region_id)
    if region is None:
        return None
    ids = list(region["element_ids"])
    for row in conn.execute(
        "SELECT from_region, to_region FROM links WHERE from_region = ? OR to_region = ?"
        " LIMIT 50",  # a hub chunk must not pull in the whole canvas
        (region_id, region_id),
    ):
        other = row["to_region"] if row["from_region"] == region_id else row["from_region"]
        linked = get_region(conn, other)
        if linked is not None and linked["status"] == "active":
            ids += linked["element_ids"]
    if by_id is None:  # a caller reading many regions passes the scene map once
        _, elements_json = get_scene(conn, region["document_id"])
        by_id = {e["id"]: e for e in json.loads(elements_json)}
    out, seen = [], set()
    for i in ids:
        e = by_id.get(i)
        if e is None or i in seen or e.get("isDeleted") or (e.get("customData") or {}).get("draft"):
            continue
        seen.add(i)
        out.append(e)
    return out
