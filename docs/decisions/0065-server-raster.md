# 0065: Server-side raster for chunk crops and thumbnails (INK-120)

Status: accepted (default stays `browser` until the owner's E1 comparison)

## Context
Only the browser could render crops (decision 0015), so a chunk had no reading until the tablet
was open, idle and saved, and `check_sync` / the worker skipped every `png_stale` chunk. Tech ref
v4 ("Server-rendered crops") moves the render to the server. A Pillow prototype drew a
100-element chunk in 126 ms to a 42 KB PNG, and `canvas/sketch_image.py` already draws ink this
way for the sketch markers.

## Decision
1. **Config.** `INKBRIDGE_CROP_SOURCE` is `browser` (default) or `server`. An invalid value warns
   on stderr and means `browser`. Read at call time. `GET /health` reports it as `crop_source`.
2. **Where it renders (server mode).** Lazily from the stored scene, in three places: the
   recognition worker before it reads a chunk, `GET /regions/{id}/image|png`
   (`db.ensure_crop`), and `GET /documents/{id}/overview` (at most `MAX_RENDER_PER_OVERVIEW = 24`
   stale chunks per call; the rest are drawn as the orange stale frame and a later call
   finishes them). Every render is `db.render_server_crop`: scene read first, region second,
   render outside the lock, then under `BEGIN IMMEDIATE` a version check plus the compare-and-set
   in `mark_png_fresh`. A save in between leaves `png_stale` set and keeps the old file, so a
   crop of older ink is never marked fresh. There is no upload and no 409.
3. **The browser upload is refused.** In server mode `PUT /regions/{id}/image` answers 403, and
   `CropSync` disposes itself after reading `crop_source` from `/health` (a failed health call
   leaves browser crops on). The 403 for an upload that slips in before the answer lands is
   covered by the per-chunk failure backoff.
4. **Not pixel-identical to Excalidraw** (`canvas/raster.py`): shapes are outlines only (fills
   are not drawn, so text inside stays visible), one stroke colour per element, no hachure and no
   roughness, text in Pillow's bundled font. Freedraw width follows pressure segment by segment
   (`scale * base * (0.35 + 1.3 * p)`, so 0.5 is 1.0x). Drafts, deleted and `transparent`
   elements are never drawn, so a crop or thumbnail never shows a draft.
5. **Scale.** At most 1.0 like the browser export, shrunk so the long side is at most 2048 px,
   padding 10 units, and at most 4 MP. The too-large rule (decision 0052, 4096 units) keeps the
   scale at 0.5 or better; a too-large chunk is never rendered and stays `png_stale`.
- `check_sync` (`needs_reading`) treats a stale chunk as readable in server mode, and
  `recognition_candidates(include_stale=True)` lists it; the worker renders it first. A canvas
  not in `INKBRIDGE_RECOGNIZE_DOCUMENTS` still takes the existing "worker did not accept" path.

## Thumbnail (for INK-118)
`render_thumbnail(elements, *, width=480, height=320) -> bytes` in `canvas/raster.py`: the whole
canvas fitted inside the card (aspect kept, centred, never scaled up past 1.0, 16 px margin);
an empty or draft-only canvas is a blank white card of that size. INK-118 owns the endpoint and
the cache keyed by head seq.

## Consequences
- Default `browser`: nothing changes until the owner flips it. Decision 0015 is replaced only
  then; its rules stay for browser mode. Decision 0052's too-large rule stays in both modes.
- Owner check: run the eval harness (decision 0033) with browser crops and with
  `INKBRIDGE_CROP_SOURCE=server` crops on the same pages, compare character error rate, then
  choose the default. Look at a few server crops from real pages for legibility.
- No MCP tool signature changes, so `docs/mcp-tools.md` has no new row. The MCP server stays an
  HTTP client (`tests/test_mcp_boundary.py`).
- Open question: rendering inside overview requests (about 126 ms per 100-element chunk) can
  take a request thread; capped at 24 per call. Each render re-reads and parses the scene JSON,
  which may deserve a per-pass cache if big scenes make the worker slow.
- A manual region (uploaded PNG at creation) that later goes stale is re-rendered by the server
  in server mode, since uploads are refused.
- A flood of saves can make every render lose the race; the worker retries next pass.
