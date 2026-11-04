# 0027: successor_of foreign key (and scene save cost)

Status: accepted (INK-072)

## Part 1: no foreign key on `regions.successor_of` for now (item 7)

Decision: do not add `successor_of REFERENCES regions(id)` now. Defer the table rebuild to the
migrations ADR (INK-071). A test-only guard covers the invariant meanwhile.

- SQLite cannot `ADD CONSTRAINT`. An FK means the 12-step rebuild of `regions` (create new, copy,
  drop, rename, recreate indexes, keep `region_fts`, `links` and `recognitions` consistent). That
  is the procedure INK-071 exists to define; doing it ad hoc first would set the precedent.
- `connect()` already runs `PRAGMA foreign_keys = ON` (`db/__init__.py`), so an FK would be
  enforced. Nothing deletes regions today: `grep "DELETE FROM regions" src` finds nothing (only
  `links` rows are rebuilt and `region_fts` rows removed). So `ON DELETE SET NULL` would never
  fire, and a dangling `successor_of` can only come from a bug or hand editing.
- Readers already tolerate the bad cases: `db/sync.py::_live_successor` returns None for a missing
  row, a row of another document, or a cycle (`MAX_HOPS`). "Same document" and "acyclic" are not
  expressible by a plain FK anyway.
- Interim guard: `tests/integrity_check.py::successor_problems` (missing region, other document,
  loop) runs after every test with the FTS check (`tests/conftest.py`). The existing suite passed
  it except `test_a_successor_cycle_or_dead_end_is_removed`, which writes a cycle on purpose; it
  carries the `fts_unchecked` marker, which now skips both checks. No other test leaves a bad
  `successor_of`.

Revisit when INK-071 lands.

## Part 2: scene save cost (item 6)

`put_scene` now logs one line per successful save on logger `inkbridge.scene` (API process
stderr, never MCP stdout): element count, changed count, and ms for parse, diff, region refresh,
chunk sync and total; `warning` above `SLOW_SAVE_S = 1.0`. A failed save logs nothing.
`tests/test_scene_timing.py` pins the log and a one-edit save on 5,000 elements under 3 s.

Benchmark, `scripts/bench_scene_save.py --sizes 5000 50000` (synthetic freedraw clusters of 5, throwaway
DB, ms, median; warm = ten saves each editing one element):

| elements | save | parse | diff | refresh | chunks | total |
|---------:|------|------:|-----:|--------:|-------:|------:|
| 5,000 | cold | 17 | 1 | 0 | 415 | 435 |
| 5,000 | warm | 29 | 3 | 0 | 130 | 164 |
| 50,000 | cold | 185 | 9 | 0 | 4571 | 4777 |
| 50,000 | warm | 344 | 36 | 2 | 1718 | 2098 |

Pure `json.loads` x2 plus `_changed_ids` on the same payload: 34 ms at 5k, 389 ms at 50k.

Rule set beforehand: a cheaper diff is clearly needed only if a warm one-edit save at 50k exceeds
1.0 s AND parse + diff is more than 40% of it. Warm 50k is 2.1 s, but parse + diff is 380 ms, 18%.
The chunk step (clustering the whole scene plus matching) is 82%. Decision: no cheaper diff; the
in-memory per-document element cache would add shared state across connections for at most a 18%
gain. If 50k pages matter, the target is `_sync_chunks`/`chunk_scene` (cluster only changed
neighbourhoods), a separate ticket. Numbers are synthetic; re-check with the save timing logs on
real pages (INK-067, INK-061).
