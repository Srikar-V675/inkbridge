"""check_sync: what changed under a note, with early cutoff (INK-036, tech ref 8.4 and 9.7).

Pure reads. A note stores, per chunk, its id, content hash and reading hash (text_hash). Two
filters in a row: an equal content hash is `fresh` (moves cost nothing); otherwise the current
reading decides between `fresh_after_reread` (same words) and `changed`.
"""

import sqlite3

from inkbridge.db import DocumentNotFound, document_exists, get_region
from inkbridge.db.outline import chunk_outline

MAX_HOPS = 64  # successor chains are short; this only guards against corrupt cycles
PREVIEW = 80


def _live_successor(conn: sqlite3.Connection, region: dict, document_id: str) -> dict | None:
    """Follow successor_of from an orphaned chunk to an active one; None on a dead end or cycle."""
    seen = {region["id"]}
    current = region
    for _ in range(MAX_HOPS):
        nxt = current.get("successor_of")
        if not nxt or nxt in seen:
            return None
        seen.add(nxt)
        current = get_region(conn, nxt)
        if current is None or current["document_id"] != document_id:
            return None
        if current["status"] == "active":
            return current
    return None


def resolve(conn: sqlite3.Connection, document_id: str, chunks: list[dict]) -> list[tuple]:
    """Per listed chunk (first occurrence of an id wins): (note, region or None, successor or None).

    region is the live row for an active chunk; successor is set for an orphaned one with a live
    successor. Both None means removed.
    """
    if not document_exists(conn, document_id):
        raise DocumentNotFound(document_id)
    out, seen = [], set()
    for note in chunks:
        if note["id"] in seen:
            continue
        seen.add(note["id"])
        region = get_region(conn, note["id"])
        if region is None or region["document_id"] != document_id:
            out.append((note, None, None))
        elif region["status"] == "active":
            out.append((note, region, None))
        else:
            out.append((note, None, _live_successor(conn, region, document_id)))
    return out


def needs_reading(resolved: list[tuple]) -> list[str]:
    """Live chunks whose status depends on a reading that does not exist yet and that the worker
    can read now (fresh crop). A stale crop cannot be read until the browser re-exports it, so
    waiting for it would only spend the whole wait: it is reported at once instead."""
    ids = []
    for note, region, successor in resolved:
        live = region if region is not None and region["content_hash"] != note["hash"] else None
        live = live or successor
        if live is not None and not live["source"] and not live["png_stale"]:
            ids.append(live["id"])
    return list(dict.fromkeys(ids))


def has_readings(conn: sqlite3.Connection, region_ids: list[str]) -> bool:
    """True once every region has a reading for its current content hash (cheap poll)."""
    return all((r := get_region(conn, i)) is None or r["source"] for i in region_ids)


def check(conn: sqlite3.Connection, document_id: str, chunks: list[dict]) -> dict:
    """resolve + classify on one read snapshot, so a save in between cannot mix two scenes."""
    conn.execute("BEGIN")  # deferred: a WAL read snapshot from the first SELECT on
    try:
        return classify(conn, document_id, resolve(conn, document_id, chunks))
    finally:
        conn.rollback()


def classify(conn: sqlite3.Connection, document_id: str, resolved: list[tuple]) -> dict:
    result: dict[str, list] = {
        "fresh": [],
        "fresh_after_reread": [],
        "changed": [],
        "replaced": [],
        "removed": [],
        "new": [],
    }
    successors = set()
    for note, region, successor in resolved:
        if region is not None:
            reading = region["text_hash"] if region["source"] else None
            item = {"id": region["id"], "hash": region["content_hash"], "reading": reading}
            if region["content_hash"] == note["hash"]:
                # Same ink. Still changed if a reading now exists that the note does not have
                # (it was exported before recognition, or a user/agent corrected the reading):
                # otherwise that text would never reach the note.
                if reading is None or reading == note.get("reading"):
                    result["fresh"].append(note["id"])
                else:
                    result["changed"].append(item)
                continue
            # No reading (null) is never a match: err towards a visible update.
            same = reading is not None and reading == note.get("reading")
            result["fresh_after_reread" if same else "changed"].append(item)
        elif successor is not None:
            successors.add(successor["id"])
            result["replaced"].append(
                {
                    "id": note["id"],
                    "successor": successor["id"],
                    "hash": successor["content_hash"],
                    "reading": successor["text_hash"] if successor["source"] else None,
                }
            )
        else:
            result["removed"].append(note["id"])
    listed = {note["id"] for note, _, _ in resolved}
    for c in chunk_outline(conn, document_id, status="active")["chunks"]:
        if c["id"] in listed or c["id"] in successors:
            continue
        text = c["text"]
        result["new"].append(
            {
                "id": c["id"],
                "hash": c["content_hash"],
                "reading": c["text_hash"] if c["source"] else None,
                "preview": text if not text or len(text) <= PREVIEW else text[: PREVIEW - 1] + "…",
            }
        )
    return result
