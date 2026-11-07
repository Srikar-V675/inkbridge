"""Canvas brief and the what-changed cursor (INK-135, decision 0093). The brief never leaves the database."""

import json
import sqlite3

from inkbridge.canvas.chunker import reading_order
from inkbridge.db.common import AUTO, DocumentNotFound, _now
from inkbridge.db.regions import _region_dict

MAX_BRIEF_CHARS = 4000
MAX_CHANGED = 100


def _head(conn: sqlite3.Connection, document_id: str) -> int:
    row = conn.execute("SELECT version FROM scenes WHERE document_id = ?", (document_id,)).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    return row["version"]


def get_memory(conn: sqlite3.Connection, document_id: str) -> dict:
    _head(conn, document_id)
    row = conn.execute(
        "SELECT brief_md, last_seen_seq, updated_at FROM canvas_memory WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        return {"brief": "", "last_seen_seq": 0, "updated_at": None}
    return {"brief": row["brief_md"], "last_seen_seq": row["last_seen_seq"], "updated_at": row["updated_at"]}


def set_brief(conn: sqlite3.Connection, document_id: str, brief: str) -> dict:
    _head(conn, document_id)
    conn.execute(
        "INSERT INTO canvas_memory (document_id, brief_md, updated_at) VALUES (?,?,?)"
        " ON CONFLICT (document_id) DO UPDATE SET brief_md = excluded.brief_md,"
        " updated_at = excluded.updated_at",
        (document_id, brief, _now()),
    )
    conn.commit()
    return get_memory(conn, document_id)


def what_changed(
    conn: sqlite3.Connection, document_id: str, since: int | None = None, mark_seen: bool = False
) -> dict:
    head = _head(conn, document_id)
    start = get_memory(conn, document_id)["last_seen_seq"] if since is None else since
    changed = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM scene_elements WHERE document_id = ? AND seq > ?", (document_id, start)
        )
    }
    found: dict[str, tuple[dict, str]] = {}
    if changed:
        for r in conn.execute(
            "SELECT * FROM regions WHERE document_id = ? AND created_by = ?"
            " AND (status = 'active' OR successor_of IS NULL)",
            (document_id, AUTO),
        ):
            if changed.isdisjoint(json.loads(r["element_ids_json"])):
                continue
            found[r["id"]] = (_region_dict(conn, r), "changed" if r["status"] == "active" else "removed")
    live = {i: c["bounds"] for i, (c, kind) in found.items() if kind == "changed"}
    ordered = reading_order(live) + sorted(i for i, (_, k) in found.items() if k == "removed")
    out = []
    for cid in ordered[:MAX_CHANGED]:
        c, kind = found[cid]
        out.append({"id": cid, "change": kind, "kind": c["kind"], "bounds": c["bounds"],
                    "text": c["text"], "latex": c["latex"], "content_hash": c["content_hash"],
                    "text_hash": c["text_hash"]})
    if mark_seen:
        conn.execute(
            "INSERT INTO canvas_memory (document_id, last_seen_seq, updated_at) VALUES (?,?,?)"
            " ON CONFLICT (document_id) DO UPDATE SET last_seen_seq = excluded.last_seen_seq",
            (document_id, head, _now()),
        )
        conn.commit()
    return {"document": document_id, "since": start, "seq": head, "marked_seen": mark_seen,
            "chunk_count": len(ordered), "omitted": max(0, len(ordered) - MAX_CHANGED), "chunks": out}
