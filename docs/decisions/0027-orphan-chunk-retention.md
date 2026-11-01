# 0027: orphaned chunks are kept (no deletion, no pool bound)

Status: accepted (INK-072)

## Question

Orphaned chunk rows are never deleted and enter `match_chunks` as candidates on every save
(`_sync_chunks` loads every `created_by='auto'` row). How large does that pool get, and should it
be bounded?

## Why they are kept

- Undo: restoring elements reactivates an orphan under its own id (`tests/test_orphan_pool.py`
  fails if orphans were dropped).
- Provenance: vault notes store chunk ids, and `check_sync` follows `successor_of` from them
  (`replaced`). The backend never reads the vault (invariant), so it cannot know which ids a note
  still names. Deleting an orphan can turn a note's `replaced` into `removed`.

## Measurement

`scripts/orphan_growth.py` (synthetic canvas, seed 0, 1,200 saves = 60 days x 20 saves; each save
randomly draws a cluster of 3-8 strokes, erases one, extends one or splits one; ids never reused):

| saves | scene elements (live / deleted) | active | orphan rows | orphan element ids | match_chunks ms | save ms | DB KB |
|------:|---------------------------------|-------:|------------:|-------------------:|----------------:|--------:|------:|
| 100 | 150 / 118 | 31 | 34 | 178 | 0.09 | 2.9 | 196 |
| 400 | 615 / 462 | 124 | 135 | 683 | 0.67 | 21.5 | 556 |
| 800 | 1141 / 975 | 225 | 284 | 1359 | 1.32 | 43.9 | 1008 |
| 1200 | 1549 / 1520 | 325 | 438 | 2132 | 2.20 | 65.5 | 1448 |

- `match_chunks` is 3.4% of a save at 438 orphans (2.2 of 65.5 ms) and about 3% throughout; it
  grows with the pool but the save grows faster (the chunker over the whole scene dominates, see
  0026). Extrapolated to 1,000 orphans it stays well under the 10% line.
- DB growth is about 1.2 MB per 1,000 saves, almost all of it the scene JSON (deleted elements stay
  in it, as Excalidraw keeps them). The orphan rows themselves are about 260 B each (element ids,
  bbox, two hashes, crop path): 1,000 orphans is about 260 KB.
- Crop files: the server never writes a crop; the browser uploads one for an active chunk with a
  stale PNG. An orphan keeps the `png_path` and any file already uploaded, and nothing removes the
  file. That is the one unbounded cost (one PNG per chunk that was ever shown), and it is disk, not
  per-save time. A cleanup of crop files of orphans older than N days is safe (a crop is
  re-rendered on reactivation because `png_stale` is set on any ink change) but is not done here.

## Decision

No deletion and no bound on the candidate pool: the 10% trigger is not met. The mitigation sketched
for that case (pass `match_chunks` only orphans updated within `ORPHAN_MATCH_DAYS` or that an active
chunk names as `successor_of`, keep every row for `check_sync`) is not implemented.

A rule that would be safe later: drop orphans older than N days that no active chunk's
`successor_of` chain reaches and that no note names. The last condition needs note-side knowledge
(ids live in vault frontmatter), which the backend cannot have; so any deletion would need an
explicit user action or a note scan by the export skill, not a timer.

The numbers are synthetic. Re-check against E5 pages (INK-061) and the save timing logs (INK-067,
`inkbridge.scene` log line from 0026).
