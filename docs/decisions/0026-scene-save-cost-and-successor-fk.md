# 0026: successor_of foreign key (and scene save cost)

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
