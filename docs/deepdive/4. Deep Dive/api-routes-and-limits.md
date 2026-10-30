# Deep Dive: API app, routes, limits and images (`api/`, `imaging.py`)

FastAPI app in `api/__init__.py` (143 lines). Routers: `chunks`, `ops`, `overrides`, `regions`, `search`, `sync`, `ws` (`:44-50`). Every handler gets a per-request connection from `Conn` (`api/deps.py:9-18`): `db.connect()` in a generator dependency, closed afterwards. Handlers that wait on SQLite locks use `run_in_threadpool`.

## Startup (`lifespan`, `api/__init__.py:18-30`)

1. `db.init_db()` migrates and ensures the `default` document.
2. `RecognitionWorker.from_env(publish=ws.hub.publish)`; if not `None`, `start()` it.
3. `app.state.recognition_worker = worker` (`check_sync` asks it for readings).
4. On shutdown `worker.stop()`.

`BodySizeLimit` middleware wraps the app (`:34`). A custom `RequestValidationError` handler returns only `loc`, `msg` and `type` (`:37-41`) because the default body echoes the offending input, which cannot be JSON-encoded when it holds NaN.

## Scene routes

`GET /documents/{id}/scene` returns `{version, elements}` (404 on unknown document). `PUT` takes `SceneIn {base_version >= 0, elements}` (`:90-105`). Validation (`_elements_valid`):
- at most `MAX_ELEMENTS = 50_000`;
- every element has a string `id`;
- no NaN or Infinity anywhere (`_all_finite`, recursive);
- `_check_geometry`: `x, y, width, height, angle` are finite numbers; `points` is a list of `[x, y, ...]` numbers; `pressures` a list of numbers. Reason: malformed shapes would crash `bbox_of` and the hashes and "wedge autosave".

The save stores compact JSON (`ensure_ascii=False`, tight separators), maps `DocumentNotFound` to 404 and `VersionConflict` to 409 `{current_version}` (the browser merges and retries). After success it publishes `chunks.updated {version, stale_crops}` to open browsers.

## Body size caps (`api/limits.py`)

Pure ASGI middleware, applied **before** any route parses a body (FastAPI reads JSON whole; Starlette spools multipart to disk first). Caps: `MAX_BODY_BYTES = 128 MiB` for scenes (a long freedraw stroke with pressures is about 35 KB, so room for a few thousand dense strokes; it bounds memory, not content); `MAX_IMAGE_BODY_BYTES = 10 MiB + 1 MiB` for `POST /documents/*/regions` and `PUT /regions/*/image`. Over the cap by `Content-Length` answers 413 at once without draining; otherwise the body is read up to the cap (covers chunked uploads without a declared length) and replayed to the app. Decision 0010.

## Region routes (`api/regions.py`)

| Route | Notes |
|---|---|
| `POST /documents/{id}/regions` | multipart `element_ids` (JSON list, deduplicated), `image` (PNG), `kind`, `created_by`; 10 MB PNG cap (`MAX_UPLOAD_BYTES`), validity checked with Pillow (`is_valid_png`, 422 otherwise). The crop **file is written first** so a row never exists without its crop; failures delete it. `created_by='auto'` is refused (422) |
| `GET /documents/{id}/regions` | `kind`, `limit` (1 to 500), `chunks`, `png_stale`, `status` filters |
| `GET /regions/{id}` | One region/chunk |
| `PUT /regions/{id}/image` | Crop sync. Body `image` plus `scene_version`. Writes to a unique temp name (`<path>.<8 hex>.tmp`) before the lock; under `BEGIN IMMEDIATE` it checks the scene version (mismatch -> 409 `{current_version}`, nothing written), atomically `tmp.replace(path)`, then `mark_png_fresh` (compare-and-set again) which commits. A crash mid-write never leaves a half crop (decision 0015) |
| `GET /regions/{id}/image` | Crop downscaled to `max_width` (1 to 8192, default 1024); stored file untouched |
| `GET /regions/{id}/ink` | Raw strokes decimated to `max_points` (2 to 100,000, default 5,000) with `original_point_count` and `decimated` |
| `GET /regions/{id}/sketch`, `/sketch.png` | Pass-1 sketch JSON with marker positions, and the marker PNG. 422 for no live ink, or more than `MAX_SKETCH_ELEMENTS = 2000` |

## Chunk routes (`api/chunks.py`)

`POST /documents` (title 1 to 200 chars, not blank; 409 `too_many_canvases` at 500) returns the document plus `url`; `GET /documents` lists canvases with deep links; `GET /documents/{id}/chunks` (`status` active/orphaned/all, `png_stale`) adds a `deep_link` per chunk; `GET /documents/{id}/overview` composites crops; `GET /regions/{id}/png` returns the stored crop at full size. `deep_link` builds `<INKBRIDGE_PUBLIC_URL>/?canvas=<id>&chunk=<id>` with percent-encoding.

## Override routes (`api/overrides.py`)

`POST /documents/{id}/chunks/merge {chunk_ids <= 100}` and `.../split {chunk_id, element_ids <= 50,000}`. Error mapping in `_run`: `DocumentNotFound` and `ChunkNotFound` -> 404, `ChunkNotActive` -> 409 ("reload the chunk list"), `InvalidOverride` -> 422. Responses `{chunk, orphaned}` and `{chunks, orphaned}`.

## Search

`GET /search?q=&limit=1..100&document_id=` returns `db.search` results.

## Images (`imaging.py`)

Pure Pillow helpers:
- `cap_width(png, 1024)`: LANCZOS downscale, never up.
- `is_valid_png`: full decode, format must be PNG.
- `decimate_strokes(strokes, max_points)`: if total points exceed the budget, keep a proportional number per stroke (floor of 2 points, then 1 if still over), sampled evenly including first and last; pressures are sampled with the same indices only if they pair 1:1 with the points, else dropped; strokes that no longer fit are skipped.
- `overview(chunks, load, max_width)`: composites crops at their canvas bounds with a 16 px pad, scale never above 1, area capped at 16M pixels (about 48 MB RGB), each chunk labelled with its id in red; a missing crop is a grey box; a stale crop gets an orange frame; transparent crops flatten onto white; `load(id)` is called one chunk at a time so only one crop is in memory.

## Testing

`test_scenes.py`, `test_limits.py` (413 for oversized, chunked and declared-length bodies, image routes using the image cap, bodyless requests unaffected), `test_regions_api.py`, `test_crop_sync.py`, `test_chunks_api.py`, `test_chunk_overrides.py`, `test_imaging.py`, `test_search.py`, `test_health.py`.

## Potential improvements

No authentication (LAN only). A worker per process; the 128 MiB scene cap is generous.
