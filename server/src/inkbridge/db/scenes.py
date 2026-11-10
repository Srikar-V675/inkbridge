"""Scene load and save: versioned element snapshot per canvas."""

import json
import logging
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from inkbridge.canvas.chunker import (
    ChunkerConfig,
)

log = logging.getLogger("inkbridge.scene")  # stderr in the API process; never MCP stdout

from inkbridge.db.chunks import _gc_orphans, _sync_chunks
from inkbridge.db.common import DocumentNotFound, _now
from inkbridge.db.elements import (
    ElementsRefused,
    n1_violations,
    read_rows,
    shrink_tombstones,
    stamp,
    wins,
    write_changed,
)
from inkbridge.db.regions import _refresh_regions

# (document, save key) -> version that save produced (INK-083, decision 0040).
# shortcut: in memory, lost on restart (a retry across a restart may 409 once); upgrade to a table if seen.
_applied: OrderedDict[tuple[str, str], int] = OrderedDict()
APPLIED_CAP = 256
SLOW_SAVE_S = 1.0  # a scene save slower than this is logged at warning (INK-072, decision 0027)


def was_applied(document_id: str, save_key: str) -> bool:
    return (document_id, save_key) in _applied


def count_live(elements: list[dict]) -> int:
    """Elements that are neither deleted nor agent drafts: the home screen's ink count."""

    def draft(e: dict) -> bool:
        data = e.get("customData")
        return isinstance(data, dict) and bool(data.get("draft"))

    return sum(1 for e in elements if not e.get("isDeleted") and not draft(e))


@dataclass
class MergeResult:
    seq: int
    newer: list[dict]
    changed: int  # rows written
    replay: bool = False
    written: list[dict] = field(default_factory=list)  # the winners this merge stored


def _stored(conn: sqlite3.Connection, document_id: str, ids: list[str]) -> dict[str, tuple]:
    """id -> (version, nonce, json) for the rows that exist, tombstone stubs included."""
    out: dict[str, tuple] = {}
    for i in range(0, len(ids), 500):  # stay under SQLite's variable limit
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
            "SELECT id, version, nonce, json FROM scene_elements"
            f" WHERE document_id = ? AND id IN ({marks})",
            [document_id, *chunk],
        ):
            out[r["id"]] = (r["version"], r["nonce"], r["json"])
    return out


def merge_elements(
    conn: sqlite3.Connection,
    document_id: str,
    elements: list[dict],
    *,
    key: str | None = None,
    base_seq: int | None = None,
    strict: bool = True,
    chunker_config: ChunkerConfig | None = None,
    max_elements: int | None = None,
    timings: dict[str, float] | None = None,
    guard: Callable[[sqlite3.Connection], None] | None = None,
    finish: Callable[[sqlite3.Connection, int], None] | None = None,
) -> MergeResult:
    """Merge a batch of elements into the scene, one element at a time (INK-111, decision 0080).

    An incoming element replaces its stored row only if it wins (`elements.wins`: higher version,
    then lower versionNonce); a batch never deletes by omission. The head bumps once, and only if a
    row changed; a batch that changes nothing touches no regions or chunks. `key` makes a retry a
    no-op that returns the first result. `base_seq` (legacy PUT) also reports rows other devices
    wrote after it. `strict` enforces N1: no draft-flagged element and no new `<op_id>:` id.

    `newer` holds the stored copy of every sent element that lost to a different (version, nonce).
    BEGIN IMMEDIATE takes the write lock first, so the compare and the write are one step; any
    error rolls the whole batch back. `timings` is filled with lock, work, commit and total in ms;
    the timer starts before the lock wait (INK-102).

    `guard(conn)` runs right after the lock and head read and may fill `elements` in place (it is
    iterated after); `finish(conn, head)` runs just before COMMIT (INK-114, drafts.py).
    """
    now = _now()
    recorded = False
    crops: list[str] = []
    timings = {} if timings is None else timings
    t_start = time.perf_counter()  # before the lock wait
    conn.execute(
        "BEGIN IMMEDIATE"
    )  # the write lock first; the merge is read-compare-write under it
    t_lock = time.perf_counter()
    timings["lock"] = round((t_lock - t_start) * 1000, 1)
    t_diff = t_refresh = t_chunks = t_lock
    write: list[dict] = []
    try:
        head_row = conn.execute(
            "SELECT version FROM scenes WHERE document_id = ?", (document_id,)
        ).fetchone()
        if head_row is None:
            raise DocumentNotFound(document_id)
        head = head_row["version"]
        if guard is not None:
            guard(conn)
        if key is not None and (document_id, key) in _applied:
            conn.rollback()  # a retry of a batch that already landed: replay its seq
            return MergeResult(_applied[(document_id, key)], [], 0, replay=True)
        best: dict[str, dict] = {}  # one winner per id inside the batch, by the same rule
        for e in elements:
            cur = best.get(e["id"])
            if cur is None or wins(*stamp(e), *stamp(cur)):
                best[e["id"]] = e
        stored = _stored(conn, document_id, list(best))
        if strict:
            refused = n1_violations(list(best.values()), set(stored))
            if refused:
                raise ElementsRefused(refused)
        newer: list[dict] = []
        for i, e in best.items():
            row = stored.get(i)
            if row is None or wins(*stamp(e), row[0], row[1]):
                write.append(e)
            elif stamp(e) != (row[0], row[1]):
                newer.append(json.loads(row[2]))
        if base_seq is not None:  # legacy PUT: what others wrote since the client's last head
            newer += [
                json.loads(r["json"])
                for r in read_rows(conn, document_id, stubs=True, since=base_seq)
                if r["id"] not in best
            ]
        if max_elements is not None and write:
            total = conn.execute(
                "SELECT COUNT(*) FROM scene_elements WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            if total + sum(1 for e in write if e["id"] not in stored) > max_elements:
                raise SceneTooLarge(total)
        t_diff = time.perf_counter()
        if write:
            # first statement of the write phase: tests/test_chunk_persistence.py::_RacingConn races here
            conn.execute(
                "UPDATE scenes SET version = version + 1, updated_at = ? WHERE document_id = ?",
                (now, document_id),
            )
            head += 1
            ids = {e["id"] for e in write}
            write_changed(conn, document_id, write, ids, head, now)
            shrink_tombstones(conn, document_id, now)
            all_elements = [json.loads(r["json"]) for r in read_rows(conn, document_id)]
            by_id = {e["id"]: e for e in all_elements}
            conn.execute(
                "UPDATE scenes SET element_count = ? WHERE document_id = ?",
                (count_live(all_elements), document_id),
            )
            _refresh_regions(conn, document_id, by_id, ids, now)
            t_refresh = time.perf_counter()
            _sync_chunks(conn, document_id, all_elements, by_id, ids, now, chunker_config)
            crops = _gc_orphans(conn, document_id, now)
            t_chunks = time.perf_counter()
            conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
        if key is not None:  # recorded under the write lock, so a blocked retry sees it
            _applied[(document_id, key)] = head
            recorded = True
            while len(_applied) > APPLIED_CAP:
                _applied.popitem(last=False)
        if finish is not None:
            finish(conn, head)
        t_c0 = time.perf_counter()
        conn.commit()
        t_end = time.perf_counter()
        timings["work"] = round((t_c0 - t_lock) * 1000, 1)
        timings["commit"] = round((t_end - t_c0) * 1000, 1)
        timings["total"] = round((t_end - t_start) * 1000, 1)
        for path in crops:  # after the commit: a rollback must not lose files
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                log.debug("could not remove crop %s", path)
    except BaseException:
        if recorded:
            _applied.pop((document_id, key), None)
        conn.rollback()
        raise
    log.log(
        logging.WARNING if timings["total"] / 1000 > SLOW_SAVE_S else logging.INFO,
        "put_scene doc=%s elements=%d changed=%d parse=%.0fms diff=%.0fms refresh=%.0fms"
        " chunks=%.0fms %s",
        document_id,
        len(elements),
        len(write),
        0.0,
        (t_diff - t_lock) * 1000,
        (t_refresh - t_diff) * 1000 if write else 0.0,
        (t_chunks - t_refresh) * 1000 if write else 0.0,
        " ".join(f"{k}={v:.0f}ms" for k, v in timings.items()),
    )
    return MergeResult(head, newer, len(write), written=write)


def put_scene(
    conn: sqlite3.Connection,
    document_id: str,
    base_version: int,
    elements_json: str,
    chunker_config: ChunkerConfig | None = None,
    delta: bool = False,
    max_elements: int | None = None,
    save_key: str | None = None,
    timings: dict[str, float] | None = None,
) -> int:
    """Merge a scene body and return the head seq (db/outline.py, tests and scripts use this).

    `base_version` and `delta` are accepted and ignored: a full list and a delta are the same
    merge, and nothing here conflicts (decision 0080). N1 is not enforced on this path.
    """
    # INK-114: drop this flag (legacy PUT keeps storing drafts until drafts leave the scene)
    return merge_elements(
        conn,
        document_id,
        json.loads(elements_json),
        key=save_key,
        strict=False,
        chunker_config=chunker_config,
        max_elements=max_elements,
        timings=timings,
    ).seq


class SceneTooLarge(Exception):
    def __init__(self, count: int):
        super().__init__(f"too many elements: {count}")


def _changed_ids(old_elements: list[dict], new_by_id: dict[str, dict]) -> set[str]:
    """Ids added, removed or edited since the last save (tech ref gap 7).

    Excalidraw bumps `version` on every edit, but comparing whole elements is just as cheap on
    parsed JSON and stays right for clients that do not bump it. Volatile-field churn counts as a
    change here; the hashes then come out equal and nothing is written.
    """
    old_by_id = {e["id"]: e for e in old_elements}
    changed = {i for i, e in new_by_id.items() if old_by_id.get(i) != e}
    return changed | (old_by_id.keys() - new_by_id.keys())
