"""Scene load and save: versioned element snapshot per canvas."""

import json
import logging
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path

from inkbridge.chunker import (
    ChunkerConfig,
)

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.chunks import _gc_orphans, _sync_chunks
from inkbridge.db.common import DocumentNotFound, _now
from inkbridge.db.documents import get_scene
from inkbridge.db.regions import _refresh_regions

# (document, save key) -> version that save produced (INK-083, decision 0040).
# shortcut: in memory, lost on restart (a retry across a restart may 409 once); upgrade to a table if seen.
_applied: OrderedDict[tuple[str, str], int] = OrderedDict()
APPLIED_CAP = 256
SLOW_SAVE_S = 1.0  # a scene save slower than this is logged at warning (INK-072, decision 0027)


class VersionConflict(Exception):
    def __init__(self, current_version: int):
        super().__init__(f"scene is at version {current_version}")
        self.current_version = current_version


def was_applied(document_id: str, save_key: str) -> bool:
    return (document_id, save_key) in _applied


def put_scene(
    conn: sqlite3.Connection,
    document_id: str,
    base_version: int,
    elements_json: str,
    chunker_config: ChunkerConfig | None = None,
    delta: bool = False,
    max_elements: int | None = None,
    save_key: str | None = None,
) -> int:
    """Store the scene if base_version is current; return the new version.

    With `delta`, `elements_json` holds only the elements that changed since base_version: each
    replaces the stored element with its id (in place) or is appended. Nothing is removed, because
    Excalidraw keeps deleted elements (`isDeleted`) in the scene. base_version pins the stored
    scene to what the client diffed against, so a stale client gets a conflict, never a bad merge.

    BEGIN IMMEDIATE takes the write lock before the old scene is read, and the UPDATE compares
    the version again, so two writers with the same base_version cannot both win even if one
    guard is lost. Regions and chunks are re-derived in the same transaction, so they never
    disagree with the stored scene; any error rolls the whole save back.
    """
    now = _now()
    recorded = False
    crops: list[str] = []
    conn.execute("BEGIN IMMEDIATE")  # read the old scene and replace it under one write lock
    try:
        old = conn.execute(
            "SELECT version, elements_json FROM scenes WHERE document_id = ?", (document_id,)
        ).fetchone()
        if old is None:
            raise DocumentNotFound(document_id)
        if save_key is not None and (document_id, save_key) in _applied:
            conn.rollback()  # a retry of a save that already landed: replay its version
            return _applied[(document_id, save_key)]
        if old["version"] != base_version:
            raise VersionConflict(old["version"])
        old_elements = json.loads(old["elements_json"])
        if delta:
            elements_json = json.dumps(
                _apply_delta(old_elements, json.loads(elements_json)),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        cur = conn.execute(
            "UPDATE scenes SET version = version + 1, elements_json = ?, updated_at = ?"
            " WHERE document_id = ? AND version = ?",
            (elements_json, now, document_id, base_version),
        )
        if cur.rowcount == 0:  # second guard: only reachable if the write lock was not held
            raise VersionConflict(get_scene(conn, document_id)[0])
        t0 = time.perf_counter()
        elements = json.loads(elements_json)
        if max_elements is not None and len(elements) > max_elements:
            raise SceneTooLarge(len(elements))
        by_id = {e["id"]: e for e in elements}
        t1 = time.perf_counter()
        changed = _changed_ids(old_elements, by_id)
        t2 = time.perf_counter()
        _refresh_regions(conn, document_id, by_id, changed, now)
        t3 = time.perf_counter()
        _sync_chunks(conn, document_id, elements, by_id, changed, now, chunker_config)
        crops = _gc_orphans(conn, document_id, now)
        t4 = time.perf_counter()
        conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
        if save_key is not None:  # recorded under the write lock, so a blocked retry sees it
            _applied[(document_id, save_key)] = base_version + 1
            recorded = True
            while len(_applied) > APPLIED_CAP:
                _applied.popitem(last=False)
        conn.commit()
        for path in crops:  # after the commit: a rollback must not lose files
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                log.debug("could not remove crop %s", path)
    except BaseException:
        if recorded:
            _applied.pop((document_id, save_key), None)
        conn.rollback()
        raise
    total = time.perf_counter() - t0
    log.log(
        logging.WARNING if total > SLOW_SAVE_S else logging.INFO,
        "put_scene doc=%s elements=%d changed=%d parse=%.0fms diff=%.0fms refresh=%.0fms"
        " chunks=%.0fms total=%.0fms",
        document_id,
        len(elements),
        len(changed),
        (t1 - t0) * 1000,
        (t2 - t1) * 1000,
        (t3 - t2) * 1000,
        (t4 - t3) * 1000,
        total * 1000,
    )
    return base_version + 1


class SceneTooLarge(Exception):
    def __init__(self, count: int):
        super().__init__(f"too many elements: {count}")


def _apply_delta(old_elements: list[dict], changed: list[dict]) -> list[dict]:
    new_by_id = {e["id"]: e for e in changed}
    merged = [new_by_id.pop(e["id"], e) for e in old_elements]
    return merged + list(new_by_id.values())  # ids not stored yet, in the order sent


def _changed_ids(old_elements: list[dict], new_by_id: dict[str, dict]) -> set[str]:
    """Ids added, removed or edited since the last save (tech ref gap 7).

    Excalidraw bumps `version` on every edit, but comparing whole elements is just as cheap on
    parsed JSON and stays right for clients that do not bump it. Volatile-field churn counts as a
    change here; the hashes then come out equal and nothing is written.
    """
    old_by_id = {e["id"]: e for e in old_elements}
    changed = {i for i, e in new_by_id.items() if old_by_id.get(i) != e}
    return changed | (old_by_id.keys() - new_by_id.keys())
