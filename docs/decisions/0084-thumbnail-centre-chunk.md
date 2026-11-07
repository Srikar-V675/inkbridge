# 0084: Home thumbnails show the centre chunk (INK-179)

Status: accepted. Owner checks pending: look at the thumbnails of the real canvases on the tablet (is the centre chunk the one you would pick, is it large enough to read); decide whether "centre chunk" should become "last edited chunk" (see "Changing the choice later").

## Context

Decision 0070 fitted the body of the ink into the thumbnail. On a real page (hundreds of strokes at mixed sizes) that is still a whole-page texture that reads as noise at card size. The owner's fallback on 7 Nov: put the centre element in the thumbnail for now.

## Decision

1. **`render_thumbnail(elements, *, width, height, chunks=None)`.** `chunks=None` keeps the 0070 whole-canvas fit exactly (it is also the fallback). `chunks=[...]` (bbox dicts `{x, y, width, height}`, possibly empty) turns on centre focus. Drafts and deleted elements are dropped before any choice (`_drawable`), so they never draw and never move the centre.
2. **Pure selection** in `canvas/thumb_focus.py`, on plain boxes `(x0, y0, x1, y1)`:
   - Centre = median of primitive-centre x and of y over all drawable primitives (a far outlier does not move it).
   - Centre chunk = the chunk whose box centre is nearest the centre. Ties (two equal clusters): bigger area, then smaller y, then smaller x. The top-left cluster wins, on any input order.
   - Tiny centre chunk (longest side under `TINY_SHARE` = 5 percent of the extent, where the extent is `_fit_box`, so a far stray cannot make everything tiny): grow to include chunks whose gap to it is at most one chunk-width (floor `MIN_SIDE` = 20 units), nearest first, stopping before the union's longest side would pass `GROW_CAP_SHARE` = 25 percent of the extent (never below the chunk's own side).
   - No chunks yet: seed = the primitive nearest the centre, then a single-link flood (gap = max(seed side, `FLOOD_GAP_MIN` = 30)) up to `FLOOD_MAX` = 60 primitives; the box is their union. A lone sketch still works, a far stray is not in it.
3. **Drawn primitives** are those whose centre is inside the focus box grown by `FOCUS_SLACK` (5 percent of its side) + 4 units, so rotated or slightly overhanging members stay and a long arrow crossing the box does not draw as a stray line. If none qualify (stale chunk boxes), the whole-canvas fit is used.
4. **Frame.** Bounds of the drawn primitives, 16 card px margin as before, scale cap `FOCUS_MAX_SCALE` = 3.0 card px per canvas unit (the whole fit keeps 1.0), so a small chunk is shown large. The stroke floors, tiny-text bars and decimation of 0070 apply unchanged. Checked in the browser on the Home board: the real-scale fixture's paragraph, a tiny square with two neighbours, two clusters, a diagram and a sparse sketch with a far stray each show one recognisable chunk; 3.0 stayed.
5. **Chunk boxes come from `regions`** through `db.active_chunk_bounds(conn, document_id)`: active auto chunks, one SELECT, no recognition join. They are rewritten inside every scene save, so they match the scene version the thumbnail is cached under. Elements still come through `db.get_scene`. A save landing between the two reads can leave one stale thumbnail until the next save; accepted.
6. **Cache.** `THUMB_REVISION` 2 to 3 (file name and ETag already carry it; old files are removed on the next render). Nothing else in the cache code changed.

Supersedes the fit part of 0070 for the API path; the 0070 fit remains the fallback and the `chunks=None` path.

## Consequences

- Far strays and the other chunks never appear in a thumbnail.
- On a lopsided page the centre chunk can be a surprising one: the median centre follows where the primitives are, so a dense scribble pulls it. Two equal clusters show the top-left one.
- A canvas with several chunks shows only one of them; the card no longer says how much ink the page holds (the "N chunks" line does).
- Render time on the 641-element fixture stays under 300 ms (test).

## Changing the choice later (note only, no code)

"Last edited chunk": pick the active chunk with the greatest `regions.updated_at` instead of the median-centre nearest one, in `thumb_focus.choose_focus` (pass each chunk's `updated_at` along with its box, from `db.active_chunk_bounds`). The thumbnail cache is keyed on the scene version only, and every save bumps it, so it already refreshes after each edit.
