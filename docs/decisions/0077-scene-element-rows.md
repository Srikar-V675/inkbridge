# 0077 Scene element rows: migration 0008 and live-only load (INK-110)

Status: accepted. Tablet check and the two-device conflict check pending (owner).

## Context
A canvas was one JSON array in `scenes.elements_json`. On the owner's `default`, 642 of 824 elements and
1.33 MB of 1.70 MB were deleted ink: downloaded on every load and parsed on every save. Tech ref v4
sections 2 and 3 want one row per element, so a save writes what changed and a load sends live ink only.

## Decision
- **Table** `scene_elements(document_id, id, pos, seq, version, nonce, is_deleted, json, updated_at)`,
  PK `(document_id, id)`, index `(document_id, seq)` (migration **0008**; the ticket text says 0006).
  `scenes.version` is the head `seq`; every successful save still bumps it by exactly 1 (even when no row
  changed), so `base_version` and the idempotency keys behave as before. Rows a save touched get that `seq`.
- **`pos` is an addition to the ticket's columns.** The scene was an ordered array and callers (chunker
  reading order, thumbnails, `get_scene` users) see that order. A delta save keeps an element's slot and
  appends new ids. A rowid cannot carry that (VACUUM may renumber it for a text-PK table) and the
  fractional `index` is missing on old elements. `pos` is set when the row is first inserted
  (`MAX(pos)+1`) and never rewritten.
- **`json` is the element as received** (`separators=(",", ":")`, `ensure_ascii=False`), so `pressures`,
  `simulatePressure` and float spelling survive (decision 0002 per row). `version`, `nonce`, `is_deleted`
  are copies; a missing or non-numeric version is stored as 0.
- **The blob is retired, not dropped.** `scenes.elements_json` is no longer written or read after 0008
  (only 0008's own backfill reads it). It stays one release as a rollback aid; a later migration drops it.
  The version-4 heals (`_backfill_v2`, `_rekey_integral_hashes`) read the rows once 0008 exists.
- **Backfill** runs inside the migration transaction, only in the run that applied 0008, so a canvas
  emptied later is never refilled. A duplicate id in one blob keeps the last element at the first slot.
- **Tombstones.** A deleted row keeps its full JSON for 14 days (`TOMBSTONE_DAYS`, the same number as
  `ORPHAN_MAX_AGE_DAYS`), then shrinks to `{id, version, versionNonce, isDeleted: true}` with `seq` and
  `updated_at` unchanged, so `since` still reports it. A stub is a deleted row without a `type`. Internal
  readers (`get_scene`, the chunker, hashes, crops, thumbnails) skip stubs. The agent-op check does not
  (`get_scene(..., stubs=True)` in `db/ops.py`): a long-deleted element's id is still taken, so a payload
  naming it is refused (`test_op_payload_naming_a_tombstoned_id_is_refused` fails without it). Shrinking
  runs in every save; backfilled rows carry the scene's `updated_at`, so they first shrink 14 days after
  the migration.
- **A full (non-delta) PUT hard-deletes stored ids it omits** (the blob replace did the same; Excalidraw
  never omits ids, only tests do). It does not re-order existing rows. A shortcut, noted here.
- **Load.** `GET /documents/{id}/scene` returns `{"seq", "version", "elements"}`: live rows in `pos` order,
  row text joined with commas and never re-encoded. `version` is an alias of `seq` so the unchanged web
  client and open old tabs keep working until INK-111 moves them to `seq`. Agent drafts are still scene
  elements (until INK-114), so they count as live. Each GET logs
  `scene GET doc= seq= elements= bytes= ms=` on `inkbridge.scene`.
- **`?deleted=true`** returns deleted rows (not stubs) as well. Not in the ticket: the web conflict reload
  (`SceneSync.resolveConflict`) merges with `mergeReport`, which keeps any local element the server list
  lacks, so a live-only reload would resurrect a stroke another device deleted. Only the 409 reload asks
  for it; a normal open does not (`sceneSync.ts`, a small approved change).
- **`GET /documents/{id}/elements?since=N`** (`N >= 0`) returns `{"seq": head, "elements": [...]}`: every
  row with `seq > N`, deleted rows and stubs included, in `pos` order.
- `scripts/snapshot_canvas.py --db` reads the rows when the table exists; its API branch asks for
  `?deleted=true` so a snapshot keeps its old content.

## Numbers
`scripts/bench_scene_load.py` (INK-095 fixture, in process, identity encoding; `--deleted-ratio` added
here to pad the fixture with deleted strokes).

| | before | after |
|---|---|---|
| fixture as is (641 stored, 8 deleted) | 536 081 B, 123 651 B gzip, 7 ms | 528 703 B, 121 473 B gzip, 7 ms |
| padded to 78 % deleted (2913 stored, 633 live) | about 2 475 KB (the `?deleted=true` body) | 528 703 B, 121 473 B gzip, 8 ms |

The fixture itself has few deleted elements, so its gain is small (about 1 %); the padded run shows the
effect on a canvas shaped like `default` (78 % deleted): the load drops to about a fifth. The 1.7 MB
figure from the ticket needs the owner's real canvas; that is not required for this ticket.

## Consequences
- **One-way migration. Back up first**, with the API stopped:
  `sqlite3 data/inkbridge.db ".backup data/inkbridge.pre-0008.db"` (or `cp`). Rolling back means restoring
  that file; the old code would read a blob that no longer receives saves.
- `put_scene` still reads and parses every non-stub row and hands the chunker the full list. The win here
  is smaller loads and writes, not a faster save. INK-111 should make a save read only what it needs; the
  row helpers are in `db/elements.py` (`read_rows`, `write_changed`, `remove_rows`, `shrink_tombstones`).
- A client that was offline for long and reconnects with a stale local copy is INK-111's problem (`since`).
- The backfill reads every canvas blob inside the migration lock; a very large private database makes the
  first start slow (bounded by `MIGRATE_LOCK_TIMEOUT_MS`).
- A deleted element that has no `type` is already a "stub" by the test above and is hidden from
  `get_scene`. The API does not require `type`; accepted.
- Test helper `server/tests/scene_rows.py` replaces tests writing `scenes.elements_json`.
