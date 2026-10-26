# 0016: Chunks API, deep links and the overview

Status: accepted (INK-033). Refines tech ref 7.2. Code: `api/chunks.py`, `db/outline.py`, `imaging.overview`.

- **`GET /documents/{id}/chunks`** returns `{document, version, chunk_count, chunks[]}` in reading order
  (`chunker.reading_order`). Each chunk: `id, order, kind, bounds, element_ids, text, latex, source,
  status, successor_of, png_stale, content_hash, text_hash, links[{to, kind}], deep_link`. Links are
  listed on the chunk they leave. `order` is the 1-based position among the canvas's **active** chunks,
  computed before filters, so `?png_stale=1` still tells where each chunk sits on the page.
  `?status=active|orphaned|all` (default `active`); orphaned chunks have `order: null` and follow by id.
  The reading per chunk costs one indexed query (fine for hundreds of chunks).
- **Interim route kept.** `GET /documents/{id}/regions?chunks=true` (INK-031) is unchanged, so open
  branches that use it (INK-035 overlay, INK-057 crop sync, with their own `png_stale` / `status`
  params) keep working; they should move to `/chunks`, which has the same filters.
- **Deep links**: `<INKBRIDGE_PUBLIC_URL>/?canvas=<id>&chunk=<chunk_id>` (ids URL-encoded, trailing slash
  of the base dropped). Default base `http://localhost:5173` (the Vite dev server on this machine);
  set a `.local` name such as `http://laptop.local:5173` so links opened from the vault survive an IP
  change. Canvases get `url` without `chunk`.
- **Overview** (`GET /documents/{id}/overview?max_width=`, 64 to 8192, default 1024): a Pillow composite
  of the stored crops of active chunks, each resized into its bounds and labelled with its id (red,
  default bitmap font). Missing or undecodable crops are grey boxes; stale crops get an orange frame.
  Crude on purpose: no Excalidraw rendering on the server. Never scaled up; at most `max_width` (64 to
  4096) wide and 16 Mpx in area, so a tall canvas cannot produce a huge image. Crops are loaded and
  shrunk one at a time and flattened onto white (transparent backgrounds would otherwise turn black).
  Empty canvas: a blank 64 px PNG.
- **`GET /regions/{id}/png`** returns the stored file byte for byte; 404 for an unknown region and a
  separate 404 when no crop has been uploaded yet (new chunks until INK-057 syncs them).
- **Canvases** (`documents.updated_at` moves only on scene saves, so `GET /documents` sorts by last
  drawing): `POST /documents {title}` (1 to 200 chars, trimmed, not blank) creates a random 12-hex id (a collision is
  astronomically unlikely and would surface as a 500) and an
  empty scene at version 0; `GET /documents` lists `{id, title, updated_at, version, url}` newest first.
- **404s carry a next step** (`GET /documents lists the canvases`) on the new routes; older routes keep
  their messages.
