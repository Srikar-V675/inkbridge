# Deep Dive: database layer (`server/src/inkbridge/db/` and `regions.py`)

`db/__init__.py` (947 lines) is the only module that touches SQLite; the MCP server must not import it (boundary test `test_mcp_boundary.py`). `regions.py` holds the pure maths (bbox and the three hashes). `db/ops.py`, `db/sync.py` and `db/outline.py` are covered in their own pages.

## Connection and migrations

- `connect()` (`db/__init__.py:37-44`): `check_same_thread=False`, `Row` factory, `foreign_keys = ON`, WAL journal so readers do not block behind the scene writer.
- `migrate()` (`:51-73`): applies numbered `.sql` files from `db/migrations/` inside one `BEGIN IMMEDIATE`, which doubles as a cross-process lock (a second API process or worker waits up to `MIGRATE_LOCK_TIMEOUT_MS = 120_000`, then finds the versions recorded). A failure rolls everything back (decision 0010). `isolation_level` is switched to manual so the sqlite3 module cannot commit under it.
- `_apply_migration` runs statements one by one (`_statements` splits on `;` but keeps semicolons in strings and triggers via `sqlite3.complete_statement`), not `executescript`, because that would commit and drop the lock.
- After migration 0004, `_backfill_v2` fills `content_hash` on regions, re-keys current readings, adds `text_hash`, and rebuilds the FTS rows. It is triggered by "any region with NULL content_hash", so it also heals an interrupted backfill. `_rekey_integral_hashes` runs on every start and moves a region whose stored hash is the *legacy* form of its current ink to the new form (decision 0005: browser JSON gives `15`, a drag yields `15.0`).
- Migrations: `0001_init`, `0002_region_png_stale`, `0003_region_fts`, `0004_v2` (schema v2: `successor_of`, `content_hash`, recognitions rebuilt with `content_hash` and `text_hash`, `links`, `questions`, `agent_ops` columns), `0005_chunk_pins`. See [data model](#tables).

## Tables

| Table | Notes |
|---|---|
| `documents`, `scenes` | `scenes.version` is the optimistic lock |
| `regions` | Manual regions and auto chunks (`created_by='auto'`); `status` active/orphaned; `png_stale`; `successor_of`; `pinned` |
| `recognitions` | PK `(region_id, content_hash, source)` |
| `region_fts` | FTS5 (`text`, `latex`) holding the best reading for the current content hash |
| `links` | Arrow links between chunks, rebuilt on every save |
| `agent_ops`, `questions` | See ops page; questions has no API yet |

## Saving a scene (`put_scene`, `:227-268`)

```mermaid
sequenceDiagram
  participant API
  participant DB as put_scene
  API->>DB: put_scene(doc, base_version, elements_json)
  DB->>DB: BEGIN IMMEDIATE (write lock)
  DB->>DB: read old scene; version != base? raise VersionConflict
  DB->>DB: UPDATE scenes SET version+1 WHERE version = base (second guard)
  DB->>DB: _changed_ids(old, new)
  DB->>DB: _refresh_regions (manual regions)
  DB->>DB: _sync_chunks (chunker, match ids, upsert, orphan, rebuild links)
  DB->>DB: UPDATE documents.updated_at, COMMIT
  Note over DB: any exception -> ROLLBACK the whole save
```

`_changed_ids` (`:271-280`) compares whole elements (added, removed or edited). Volatile-field churn counts as a change here but the hashes then come out equal and nothing is written.

### `_refresh_regions` (`:417-460`, manual regions)

Only regions holding a changed element are examined. New `stroke_hash`: flag `png_stale = 1`. New `content_hash`: the ink changed, so `_reindex_region` drops the old reading from search. Status becomes `orphaned` if every element is deleted. Written only when something differs, so unrelated edits leave `updated_at` alone. A pure move changes only `stroke_hash`, so the reading and search hit survive.

### `_sync_chunks` (`:463-556`)

1. Load all auto chunk rows; collect pins (active pinned rows).
2. `chunk_scene(...)`, boxes, `match_chunks(...)` (see [chunker.md](chunker.md)); unmatched clusters get `uuid4().hex[:12]`.
3. For each cluster: skip if same elements, still active, and none changed (`:513-515`); insert if new (`_insert_chunk`, `png_stale = 1`, crop path `crops_dir()/<id>.png`); skip if only volatile fields moved (`:521`); otherwise update elements, bbox, hashes, `status='active'`, `successor_of=NULL`, pin flag, and set `png_stale` when `stroke_hash` changed. `kind` is recomputed only if the content hash changed. A content change reindexes (drops the search row).
4. Orphan every unmatched old active chunk with its `successor_of` (`:544-549`) and clear its pin.
5. Delete and re-insert all `links` rows for the document.

Test coverage: `test_chunk_persistence.py` (ids, successors, undo reactivation, rollback on failure, two racing writers, 2,000-element performance, restart re-keying).

## Manual overrides (`merge_chunks`, `split_chunk`, `_override`, `:602-703`)

Under `BEGIN IMMEDIATE`, the new pinned chunks are inserted with exactly the pinned ink, then `_sync_chunks` is called with an empty `changed` set; the matcher keeps the new ids (Jaccard 1) and orphans the originals with `successor_of`. A guard raises `RuntimeError` if that did not happen. Errors: `ChunkNotFound`, `ChunkNotActive` (stale chunk list), `InvalidOverride` (fewer than two ids, connector-only chunks, selection not inside the chunk, nothing left behind). The scene is read, never written.

## Regions and readings

- `create_region` computes bbox and hashes from the stored scene, never the client; `created_by='auto'` is reserved (`ReservedCreator`).
- `_BEST_RECOGNITION` (`:294`): precedence `user` > `agent` > `gemini`, newest first. `_region_dict` joins the best reading at the region's current `content_hash`.
- `save_recognition` upserts and reindexes; `save_model_reading` also lets a Gemini reading set an auto chunk's `kind` if the hash still matches.
- `recognition_candidates` and `read_fresh_crop` feed the worker (see recognition page).
- `mark_png_fresh(region, scene_version)` is a compare-and-set on the scene version in one statement, so a crop of older ink is never marked fresh (INK-057).
- `list_regions(chunks=False)` selects manual or auto via `created_by IS NOT ?` / `IS ?`.
- `get_sketch_elements` returns a region's elements plus one hop of linked regions (limit 50) for sketch reading; `get_region_ink` returns raw strokes.

## Search

`_fts_query` turns free text into quoted prefix tokens (`"foo"* "bar"*`, ANDed). `search` joins `region_fts` to active regions, scores `-bm25` and snippets with `[ ]`.

## `regions.py` (pure maths)

| Function | Purpose |
|---|---|
| `bbox_of` (`:33`) | Bounds of live elements; strokes use point extents (points are relative and may be negative), others x/y/width/height; rotation ignored |
| `stroke_hash` (`:23`) | SHA-256 of rows with `HASH_FIELDS` (id, type, x, y, width, height, angle, points, pressures, isDeleted), sorted by id |
| `content_hash` (`:88`) | Drops deleted; rows of `_CONTENT_FIELDS` plus `dx`,`dy` offsets from the bbox origin rounded to 0.001; integral floats become ints (`_integral`); sorted by `(round(dy), round(dx), canonical(row))` so order and ids do not matter |
| `legacy_content_hash` (`:99`) | Pre-INK-031 form, only for re-keying |
| `text_hash` (`:119`) | Normalised (`" ".join(s.split())`) text and latex |

Never hash `version`, `versionNonce`, `updated`, `seed` or `customData`.

## Potential improvements

`db/__init__.py` is oversized; INK-068 splits it into a package, INK-070 weighs SQLAlchemy and INK-071 Alembic (see roadmap).
