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
    """Live chunks whose state depends on a reading that does not exist yet."""
    ids = []
    for note, region, successor in resolved:
        if region is not None and region["content_hash"] != note["hash"] and not region["source"]:
            ids.append(region["id"])
        elif successor is not None and not successor["source"]:
            ids.append(successor["id"])
    return list(dict.fromkeys(ids))


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
            if region["content_hash"] == note["hash"]:
                result["fresh"].append(note["id"])
                continue
            reading = region["text_hash"] if region["source"] else None
            item = {"id": region["id"], "hash": region["content_hash"], "reading": reading}
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
