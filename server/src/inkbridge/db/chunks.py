"""Chunk persistence: sync on save, orphan collection, manual merge and split."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta

from inkbridge import config
from inkbridge.canvas.chunker import (
    ChunkerConfig,
    LinkRow,
    agent_op,
    chunk_scene,
    connector_ids,
    kind_hint,
    match_chunks,
    pin_groups,
    stroke_connector_ids,
)
from inkbridge.canvas.hashes import (
    bbox_of,
    content_hash,
    stroke_hash,
)
from inkbridge.canvas.strokes import analyse

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.common import AUTO, _now
from inkbridge.db.documents import get_chunker, get_scene
from inkbridge.db.recognitions import _put_recognition, _reindex_region
from inkbridge.db.regions import get_region

ORPHAN_KEEP = 40  # newest orphaned chunks kept per canvas (undo, check_sync chains; INK-087)
ORPHAN_MAX_AGE_DAYS = 14  # and none older than this (decision 0048)


def _gc_orphans(conn: sqlite3.Connection, document_id: str, now: str) -> list[str]:
    """Delete auto orphans outside the retention window; returns crop paths to unlink after commit."""
    cutoff = (datetime.fromisoformat(now) - timedelta(days=ORPHAN_MAX_AGE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT id, successor_of, updated_at, png_path FROM regions"
        " WHERE document_id = ? AND created_by = ? AND status = 'orphaned'"
        " ORDER BY updated_at DESC, id",
        (document_id, AUTO),
    ).fetchall()
    if not rows:
        return []
    by_id = {r["id"]: r for r in rows}
    keep = {r["id"] for r in rows[:ORPHAN_KEEP] if r["updated_at"] >= cutoff}
    stack = list(keep)
    while stack:  # successor chains of kept orphans stay intact
        nxt = by_id[stack.pop()]["successor_of"]
        if nxt in by_id and nxt not in keep:
            keep.add(nxt)
            stack.append(nxt)
    doomed = [r for r in rows if r["id"] not in keep]
    for i in range(0, len(doomed), 400):  # stay under SQLite's variable limit
        ids = [r["id"] for r in doomed[i : i + 400]]
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM recognitions WHERE region_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM region_fts WHERE region_id IN ({marks})", ids)
        conn.execute(
            f"DELETE FROM links WHERE from_region IN ({marks}) OR to_region IN ({marks})",
            ids + ids,
        )
        conn.execute(f"DELETE FROM regions WHERE id IN ({marks})", ids)
    return [r["png_path"] for r in doomed if r["png_path"]]


def _resolve_config(
    conn: sqlite3.Connection, document_id: str, given: ChunkerConfig | None
) -> ChunkerConfig:
    """The config for a save: an explicit one (tests), else the canvas's chunker, else the env."""
    if given is not None:
        return given
    kw = {"match_containment": config.chunk_containment()}
    if get_chunker(conn, document_id) == "v2":
        return ChunkerConfig.v2(**kw)
    return ChunkerConfig(**kw)


def _pin_exclude(cfg: ChunkerConfig, elements: list[dict]) -> set[str]:
    """Ids a pin must drop: with v2, pen connectors and heads are never chunk members."""
    return stroke_connector_ids(analyse(elements)) if cfg.version == "v2" else set()


def _sync_chunks(
    conn: sqlite3.Connection,
    document_id: str,
    elements: list[dict],
    by_id: dict[str, dict],
    changed: set[str],
    now: str,
    chunker_config: ChunkerConfig | None,
) -> None:
    """Re-run the chunker and upsert one created_by='auto' region per chunk (tech ref 5.5-5.8).

    New clusters inherit ids from old chunks (orphaned ones too, so undo reactivates them) by
    element-id Jaccard. A kept chunk whose element set is unchanged and holds no changed element
    is skipped without hashing. Chunks that lose their id become orphaned, keep their last
    element ids and hashes, and point successor_of at the cluster that took most of their ink.
    """
    cfg = _resolve_config(conn, document_id, chunker_config)
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT * FROM regions WHERE document_id = ? AND created_by = ? ORDER BY id",
            (document_id, AUTO),
        ).fetchall()
    }
    # Manual merges and splits (INK-059) are active pinned chunks: their ink stays exactly one chunk.
    pins = [
        json.loads(r["element_ids_json"])
        for r in rows.values()
        if r["pinned"] and r["status"] == "active"
    ]
    chunking = chunk_scene(elements, cfg, pins=pins)
    clusters = chunking.chunks
    old = {rid: json.loads(r["element_ids_json"]) for rid, r in rows.items()}
    boxes = [bbox_of([by_id[i] for i in members]) for members in clusters]
    matching = match_chunks(
        old,
        clusters,
        tops=[b["y"] for b in boxes],
        active={rid for rid, r in rows.items() if r["status"] == "active"},
        threshold=cfg.match_threshold,
        ignore=connector_ids(elements) | _pin_exclude(cfg, elements),
        containment=cfg.match_containment,
    )
    ids = [rid or uuid.uuid4().hex[:12] for rid in matching.assigned]

    flags = chunking.connector or [False] * len(clusters)
    for rid, kept, members, box, pinned, is_connector in zip(
        ids, matching.assigned, clusters, boxes, chunking.pinned, flags, strict=True
    ):
        row = rows.get(kept) if kept else None
        # Kept, still active and holding exactly the same elements as before. (Its pin state cannot
        # differ then: pins come from the active pinned rows themselves.)
        same = row is not None and row["status"] == "active" and old[rid] == members
        if same and changed.isdisjoint(members):
            continue  # same elements, none edited: nothing to recompute
        chunk = [by_id[i] for i in members]
        new_stroke, new_content = stroke_hash(chunk), content_hash(chunk)
        if row is None:
            _insert_chunk(
                conn,
                document_id,
                rid,
                members,
                by_id,
                now,
                pinned,
                "connector" if is_connector else None,
            )
            continue
        kind = "connector" if is_connector else None
        if (
            same
            and new_stroke == row["stroke_hash"]
            and new_content == row["content_hash"]
            and (kind or row["kind"]) == row["kind"]
        ):
            continue  # only volatile fields moved
        content_changed = new_content != row["content_hash"]
        conn.execute(
            "UPDATE regions SET element_ids_json = ?, bbox = ?, stroke_hash = ?,"
            " content_hash = ?, kind = ?, status = 'active', successor_of = NULL,"
            " pinned = ?, updated_at = ?,"
            " png_stale = CASE WHEN ? != stroke_hash THEN 1 ELSE png_stale END WHERE id = ?",
            (
                json.dumps(members),
                json.dumps(box),
                new_stroke,
                new_content,
                kind or (kind_hint(chunk) if content_changed else row["kind"]),
                int(pinned),
                now,
                new_stroke,
                rid,
            ),
        )
        if content_changed:
            _reindex_region(conn, rid)  # no reading for the new ink yet: drop the search row

    for rid, successor in matching.successors.items():
        conn.execute(
            "UPDATE regions SET status = 'orphaned', successor_of = ?, pinned = 0, updated_at = ?"
            " WHERE id = ?",
            (ids[successor] if successor is not None else None, now, rid),
        )

    # Links are derived state: rebuilt from scratch, so they only ever name current chunks.
    # Only the chunker's own rows (source 'stroke'); agent and user links are not derived from ink.
    conn.execute("DELETE FROM links WHERE document_id = ? AND source = 'stroke'", (document_id,))
    rows_ = chunking.link_rows or [LinkRow(a, b) for a, b in chunking.links]
    conn.executemany(
        "INSERT OR IGNORE INTO links (document_id, from_region, to_region, kind, source,"
        " element_id, label, confidence) VALUES (?, ?, ?, 'arrow', 'stroke', ?, ?, ?)",
        [(document_id, ids[r.a], ids[r.b], r.element_id, r.label, r.confidence) for r in rows_],
    )

    # Chunks made only of accepted agent ink are read from their own text: no crop, no model call.
    for rid, members in zip(ids, clusters, strict=True):
        if all(agent_op(by_id[i]) is not None for i in members):
            _read_agent_chunk(conn, rid, [by_id[i] for i in members])


def _read_agent_chunk(conn: sqlite3.Connection, rid: str, chunk: list[dict]) -> None:
    """Store the chunk's text elements, in reading order, as an 'agent' reading (INK-078)."""
    texts = sorted((e for e in chunk if e.get("text")), key=lambda e: (e["y"], e["x"]))
    reading = "\n".join(e["text"] for e in texts)
    h = conn.execute("SELECT content_hash FROM regions WHERE id = ?", (rid,)).fetchone()[0]
    have = conn.execute(
        "SELECT text FROM recognitions WHERE region_id = ? AND content_hash = ? AND source = 'agent'",
        (rid, h),
    ).fetchone()
    if have is None or have["text"] != reading:
        _put_recognition(conn, rid, h, "agent", reading)


def _insert_chunk(
    conn: sqlite3.Connection,
    document_id: str,
    rid: str,
    members: list[str],
    by_id: dict[str, dict],
    now: str,
    pinned: bool,
    kind: str | None = None,
) -> None:
    """A new active chunk row: hashes and bbox from the scene, crop still to be rendered."""
    chunk = [by_id[i] for i in members]
    conn.execute(
        "INSERT INTO regions (id, document_id, element_ids_json, bbox, kind, created_by,"
        " stroke_hash, content_hash, png_path, status, png_stale, pinned, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'active',1,?,?)",
        (
            rid,
            document_id,
            json.dumps(members),
            json.dumps(bbox_of(chunk)),
            kind or kind_hint(chunk),
            AUTO,
            stroke_hash(chunk),
            content_hash(chunk),
            str(config.crops_dir() / f"{rid}.png"),
            int(pinned),
            now,
        ),
    )


class ChunkNotFound(Exception):
    """No chunk with this id on this canvas (unknown, a manual region, or another canvas's)."""


class ChunkNotActive(Exception):
    """The chunk was already replaced (orphaned): the caller's chunk list is stale."""


class InvalidOverride(ValueError):
    pass


def merge_chunks(
    conn: sqlite3.Connection,
    document_id: str,
    chunk_ids: list[str],
    chunker_config: ChunkerConfig | None = None,
) -> tuple[dict, list[str]]:
    """Merge active chunks into one new pinned chunk; the originals are orphaned (INK-059).

    Returns the new chunk and the orphaned ids. The scene is only read, never written.
    """
    if len(set(chunk_ids)) != len(chunk_ids) or len(chunk_ids) < 2:
        raise InvalidOverride("merge needs at least two different chunk ids")

    def groups(rows: list[sqlite3.Row], elements: list[dict], skip: set[str]) -> list[list[str]]:
        # A chunk of nothing but arrows or lines cannot be pinned: connectors follow their ends.
        for r in rows:
            if not pin_groups(elements, [json.loads(r["element_ids_json"])], exclude=skip):
                raise InvalidOverride(
                    f"chunk {r['id']} holds only arrows or lines, which follow the chunks they "
                    "connect; merge the chunks at their ends instead"
                )
        return [[i for r in rows for i in json.loads(r["element_ids_json"])]]

    (new,), orphaned = _override(conn, document_id, chunk_ids, groups, chunker_config)
    return new, orphaned


def split_chunk(
    conn: sqlite3.Connection,
    document_id: str,
    chunk_id: str,
    element_ids: list[str],
    chunker_config: ChunkerConfig | None = None,
) -> tuple[list[dict], list[str]]:
    """Split the given elements out of a chunk: two new pinned chunks (the selection, then the
    rest) and the original orphaned with the larger part as successor (INK-059)."""
    if not element_ids:
        raise InvalidOverride("element_ids is empty: select the ink to split off")

    def groups(rows: list[sqlite3.Row], _: list[dict], __: set[str]) -> list[list[str]]:
        members = json.loads(rows[0]["element_ids_json"])
        outside = sorted(set(element_ids) - set(members))
        if outside:
            raise InvalidOverride(f"elements not in chunk {chunk_id}: {outside}")
        # pin_groups gives a shared id to the first pin, so the second is "the rest".
        return [list(element_ids), members]

    new, orphaned = _override(conn, document_id, [chunk_id], groups, chunker_config)
    return new, orphaned


def _override(conn, document_id, chunk_ids, make_groups, chunker_config):
    """Replace active chunks by new pinned chunks, then re-run the chunker in the same transaction.

    The new rows hold exactly the pinned ink, so the matcher keeps their ids (Jaccard 1) and orphans
    the originals with successor_of like any other split or merge. Nothing writes the scene.
    """
    now = _now()
    conn.execute("BEGIN IMMEDIATE")  # same lock as a scene save: the chunks cannot move meanwhile
    try:
        _, scene_json = get_scene(conn, document_id)  # raises DocumentNotFound
        rows = []
        for cid in chunk_ids:
            r = conn.execute(
                "SELECT * FROM regions WHERE id = ? AND document_id = ? AND created_by = ?",
                (cid, document_id, AUTO),
            ).fetchone()
            if r is None:
                raise ChunkNotFound(cid)
            if r["status"] != "active":
                raise ChunkNotActive(cid)
            rows.append(r)
        elements = json.loads(scene_json)
        cfg = _resolve_config(conn, document_id, chunker_config)
        skip = _pin_exclude(cfg, elements)
        wanted = make_groups(rows, elements, skip)
        groups = pin_groups(elements, wanted, exclude=skip)
        # A group with no ink of its own (only connectors, or nothing left after a split) vanishes.
        if len(groups) != len(wanted):
            raise InvalidOverride(
                "the selection must hold ink (not only arrows or lines) and leave ink behind"
            )
        by_id = {e["id"]: e for e in elements}
        conn.executemany("UPDATE regions SET pinned = 0 WHERE id = ?", [(r["id"],) for r in rows])
        new_ids = [uuid.uuid4().hex[:12] for _ in groups]
        for rid, members in zip(new_ids, groups, strict=True):
            _insert_chunk(conn, document_id, rid, members, by_id, now, pinned=True)
        _sync_chunks(conn, document_id, elements, by_id, set(), now, cfg)
        new = [get_region(conn, rid) for rid in new_ids]
        old = [get_region(conn, r["id"]) for r in rows]
        # The matcher must have kept the new ids and replaced the originals; anything else is a bug.
        if any(c is None or c["status"] != "active" for c in new) or any(
            c["status"] != "orphaned" for c in old
        ):
            raise RuntimeError("chunk override did not take effect")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return new, [r["id"] for r in rows]


def set_chunker(conn: sqlite3.Connection, document_id: str, version: str | None) -> None:
    """Choose the chunker for one canvas ('v1', 'v2', or None to follow INKBRIDGE_CHUNKER) and
    re-chunk at once, in the same lock as a scene save (INK-122, decision 0081).

    Orphan collection is left to the next save. documents.updated_at is not touched: it means the
    last ink edit.
    """
    if version not in (None, "v1", "v2"):
        raise ValueError(f"chunker must be v1, v2 or None, got {version!r}")
    now = _now()
    conn.execute("BEGIN IMMEDIATE")  # same lock as a scene save
    try:
        _, scene_json = get_scene(conn, document_id)  # raises DocumentNotFound
        conn.execute("UPDATE documents SET chunker = ? WHERE id = ?", (version, document_id))
        elements = json.loads(scene_json)
        _sync_chunks(conn, document_id, elements, {e["id"]: e for e in elements}, set(), now, None)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
