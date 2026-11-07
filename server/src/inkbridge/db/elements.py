"""Scene element rows (INK-110, decision 0077): one row per element, the element JSON kept verbatim.

`pos` fixes an element's slot in the scene array when its row is first inserted and is never
rewritten, so readers see the same order the blob had. `seq` is the scene version of the save that
last wrote the row; the scene version is the head `seq`.

A tombstone stub is a deleted row older than TOMBSTONE_DAYS whose json shrank to
{id, version, versionNonce, isDeleted}: it has no `type`, which is how readers recognise it.
"""

import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta

from inkbridge.db.common import _now

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

TOMBSTONE_DAYS = 14  # same as chunks.ORPHAN_MAX_AGE_DAYS
_STUB = "json_extract(json, '$.type') IS NULL"
_COLS = "document_id, id, pos, seq, version, nonce, is_deleted, json, updated_at"


def _int(value) -> int:
    """An element's version or nonce as an integer; a missing or non-numeric value is 0."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return 0
    return int(value)


def row_json(element: dict) -> str:
    """The text stored for one element: as received, so pressures and float spelling survive."""
    return json.dumps(element, ensure_ascii=False, separators=(",", ":"))


def read_rows(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    live_only: bool = False,
    stubs: bool = False,
    since: int | None = None,
) -> list[sqlite3.Row]:
    """Rows (id, json) in scene order. Stubs are left out unless `stubs`; `since` keeps seq > since."""
    sql, args = "SELECT id, json FROM scene_elements WHERE document_id = ?", [document_id]
    if live_only:
        sql += " AND is_deleted = 0"
    if not stubs:
        sql += f" AND NOT (is_deleted = 1 AND {_STUB})"
    if since is not None:
        sql += " AND seq > ?"
        args.append(since)
    return conn.execute(sql + " ORDER BY pos", args).fetchall()


def concat(rows: list[sqlite3.Row]) -> str:
    """A JSON array of the rows' stored text, never re-encoded."""
    return "[" + ",".join(r["json"] for r in rows) + "]"


def write_changed(
    conn: sqlite3.Connection,
    document_id: str,
    elements: list[dict],
    changed: set[str],
    seq: int,
    now: str,
) -> None:
    """Upsert the rows of `changed` ids (all present in `elements`).

    New ids append at MAX(pos)+1; an existing row keeps its pos. Version, nonce and is_deleted are
    copies of the element's own fields.
    """
    next_pos = conn.execute(
        "SELECT COALESCE(MAX(pos), -1) + 1 FROM scene_elements WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    for e in elements:
        if e["id"] not in changed:
            continue
        conn.execute(
            f"INSERT INTO scene_elements ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (document_id, id) DO UPDATE SET seq = excluded.seq,"
            " version = excluded.version, nonce = excluded.nonce,"
            " is_deleted = excluded.is_deleted, json = excluded.json,"
            " updated_at = excluded.updated_at",
            (
                document_id,
                e["id"],
                next_pos,
                seq,
                _int(e.get("version")),
                _int(e.get("versionNonce")),
                int(bool(e.get("isDeleted"))),
                row_json(e),
                now,
            ),
        )
        next_pos += 1  # a harmless gap when the id already existed


def remove_rows(conn: sqlite3.Connection, document_id: str, ids: set[str]) -> None:
    """Hard-delete rows a full save left out (Excalidraw never omits ids; only tests do)."""
    conn.executemany(
        "DELETE FROM scene_elements WHERE document_id = ? AND id = ?",
        [(document_id, i) for i in ids],
    )


def shrink_tombstones(conn: sqlite3.Connection, document_id: str, now: str | None = None) -> int:
    """Cut deleted rows older than TOMBSTONE_DAYS down to a stub; seq and updated_at stay."""
    cutoff = (datetime.fromisoformat(now or _now()) - timedelta(days=TOMBSTONE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT id, version, nonce FROM scene_elements WHERE document_id = ? AND is_deleted = 1"
        f" AND updated_at < ? AND NOT {_STUB}",
        (document_id, cutoff),
    ).fetchall()
    for r in rows:
        stub = {"id": r["id"], "version": r["version"], "versionNonce": r["nonce"], "isDeleted": True}
        conn.execute(
            "UPDATE scene_elements SET json = ? WHERE document_id = ? AND id = ?",
            (row_json(stub), document_id, r["id"]),
        )
    return len(rows)
