# 0050: The overview is drawn in reading-order bands, labels sized to the output

INK-086. Status: accepted.

## Problem

`read_canvas` attached one overview PNG, always 1024 px wide, scaled to the whole bounding box. A canvas written while zoomed in is spread out: the real `default` canvas spans about 17000 x 11000 canvas units. At that span the scale is about 0.06, so 250 unit chunks became about 15 px boxes, and the id labels (PIL's default font, no size) overlapped. The model could not tell chunks apart.

## Decision

- `imaging.plan_bands(chunks, max_width)` splits the chunks, in reading order, into consecutive bands. A band grows while its union, fitted to `max_width` (and the area cap), still draws its smallest sized chunk at least `MIN_BOX_PX = 24` px tall. A chunk shorter than 24 canvas units (a dot, a bullet) is not "sized": it is ignored when choosing bands, so it cannot cut its neighbours into one-chunk bands. Such a chunk may render below 24 px. A band always holds one chunk at least, so a chunk too small to ever reach 24 px is shown alone at its natural size, never upscaled.
- `GET /documents/{id}/overview?max_width=&offset=` draws one band, the one starting at chunk index `offset`. Headers: `X-Overview-From`, `X-Overview-Count`, `X-Overview-Total`, and `X-Overview-Next` (only when more bands follow).
- `read_canvas` takes `max_width` (256 to 1568, default 1568) and attaches up to `MAX_OVERVIEW_IMAGES = 3` bands per call, starting at its `offset`. When bands remain, the reply names the `offset` that continues. The tool text says the overview is for orientation only; a chunk is read with `get_region`.
- Labels use a font sized to the output width (about 1/60 of it, 12 to 28 px). `_place_labels` tries the spot above a box, inside its corner, then below, and moves a label to the first spot clear of the labels already placed.

## Why

- Reading-order bands keep each band a contiguous part of the page, so a model reading band by band sees the same order as the outline and the `offset` of the outline and the overview are the same index.
- Empty margins between far-apart chunks were the cause; a band over a compact stretch of the page has none.
- A compacted layout (moving chunks closer together) was rejected: it distorts geometry, and orientation depends on where things are relative to each other.
- The 24 px rule is the smallest box a model can still read a chunk id from. Splitting is cheaper than shrinking.
- The three-image cap bounds the tokens of one call. A longer canvas continues with `offset`, exactly as the outline does.
- The API default stays 1024 px for other callers; only the MCP tool defaults to 1568.

## Consequences

- A canvas spread far enough needs several calls to see all of it. The overview is orientation only; the outline and `get_region` carry the content.
- A chunk shorter than 24 canvas units is ignored for band sizing and may render below 24 px. It is not enlarged, because enlarging it would hide the page's real proportions. Interleaved dots gave 20 bands for 20 boxes before this rule (8 without the dots); with it they group as before.
- `chunk_crops` returns active chunks in reading order instead of id order. Only the overview reads it.
- Planning runs over the remaining chunks on each request, which is linear in the chunk count times the band size.
