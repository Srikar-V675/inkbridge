# 0048: Orphaned chunks are collected on scene save

INK-087. Status: accepted.

## Problem

Every edit that changes a chunk's element set orphans the old chunk row. Orphans were kept forever, with their recognitions, FTS row, links and crop PNG, so row count, save time and disk grew without bound.

## Decision

On every scene save, inside the same transaction, `_gc_orphans` deletes auto chunks with `status='orphaned'` (per canvas) that fall outside a retention window. Active chunks and manual regions are never touched.

- Keep an orphan if it is among the newest `ORPHAN_KEEP = 40` by `updated_at` (the time `_sync_chunks` orphaned it) and is at most `ORPHAN_MAX_AGE_DAYS = 14` days old.
- Close the keep set over `successor_of`: an orphan reachable by following `successor_of` from a kept orphan is kept too. This keeps `check_sync` (`_live_successor`) and op anchor resolution working for kept orphans.
- Delete the rest with their recognitions, `region_fts` row and `links`.
- Crop PNGs are unlinked after the commit, best effort, so a rollback never loses files.

## Why

- Newest-N bounds growth; the age limit stops a quiet canvas from holding stale orphans forever; undo only needs recent orphans because it matches by element ids against orphans still present.
- The backend stores no notes, so "recently referenced by a note" cannot be looked up. The 14 day window stands in for it. A note older than that, pointing at a collected orphan, reports `removed` in `check_sync`.
- In-save GC needs no new process or migration, and the cost is one indexed query per save.
- Knobs are module constants, not env vars, until someone needs to change them.

## Consequences

- Undo of an edit older than the window will not reactivate the old chunk id.
- The first save after deploying against a database with many orphans deletes them in one transaction (batched by 400).
- `merge_chunks` / `split_chunks` do not collect; the next save does.
