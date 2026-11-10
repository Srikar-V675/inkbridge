"""Diagram objects (INK-140, decision 0100): a diagram outlives its drafts, one row per diagram.

`version` stays 0 until the first Accept; only Accept (commit_version) moves the row. sqlite only:
db/ops.py and db/drafts.py import this module, never the other way round.
"""

import json
import sqlite3
import uuid

from inkbridge.db import regions


class DiagramNotFound(Exception):
    pass


class DiagramBusy(Exception):
    """The diagram's current op is not accepted yet, so there is nothing to revise."""


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "document_id": r["document_id"],
        "version": r["version"],
        "source_kind": r["source_kind"],
        "source": r["source"],
        "node_map": json.loads(r["node_map_json"]),
        "from_chunks": json.loads(r["from_chunks_json"]),
        "current_op": r["current_op"],
    }


def get(conn: sqlite3.Connection, diagram_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM diagrams WHERE id = ?", (diagram_id,)).fetchone()
    return _row(r) if r else None


def attach(
    conn: sqlite3.Connection, document_id: str, oid: str, payload: dict
) -> tuple[str, str | None]:
    """(diagram_id, revises) for a new draw_diagram op. The caller holds the write transaction."""
    if payload.get("diagram_id"):
        d = get(conn, payload["diagram_id"])
        if d is None or d["document_id"] != document_id:
            raise DiagramNotFound(payload["diagram_id"])
        cur = conn.execute(
            "SELECT status FROM agent_ops WHERE id = ?", (d["current_op"],)
        ).fetchone()
        if cur is None or cur["status"] != "accepted":
            raise DiagramBusy(d["id"])
        return d["id"], d["current_op"]
    did = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO diagrams (id, document_id, version, source_kind, source, current_op)"
        " VALUES (?, ?, 0, ?, ?, ?)",
        (did, document_id, payload.get("source_kind", "mermaid"), payload["source"], oid),
    )
    return did, None


def list_accepted(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [
        _row(r)
        for r in conn.execute(
            "SELECT d.* FROM diagrams d JOIN agent_ops o ON o.id = d.current_op"
            " WHERE d.document_id = ? AND d.version > 0 AND o.status = 'accepted' ORDER BY d.id",
            (document_id,),
        )
    ]


def commit_version(conn: sqlite3.Connection, op: dict) -> None:
    """Called from Accept's finish: the op's source becomes the diagram's current version."""
    row = get(conn, op["diagram_id"])
    ids = op["payload"].get("from_chunks") or [x["chunk"] for x in row["from_chunks"]]
    snap = []
    for i in ids:
        r = regions.get_region(conn, i)
        if r is not None:
            snap.append({"chunk": i, "text_hash": r.get("text_hash")})
    again = row["current_op"] == op["id"] and row["version"] > 0  # a repeated Accept
    conn.execute(
        "UPDATE diagrams SET source=?, source_kind=?, node_map_json=?, from_chunks_json=?,"
        " version=?, current_op=? WHERE id=?",
        (
            op["payload"]["source"],
            op["payload"].get("source_kind", "mermaid"),
            json.dumps(op["payload"].get("node_map", {})),
            json.dumps(snap),
            row["version"] if again else row["version"] + 1,
            op["id"],
            row["id"],
        ),
    )
