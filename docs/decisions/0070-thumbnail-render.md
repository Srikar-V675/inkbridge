# 0070: Canvas thumbnails that look right (INK-171)

Status: accepted. Owner checks pending: look at the thumbnails of the real canvases at card size on the tablet; confirm the panel-colour background.

## Context

The first thumbnails (INK-120 / INK-118, decision 0065) were 480 x 320 on white, scaled by at most 1.0 to the bounding box of every drawable element, strokes floored at 1 px and text drawn with an 8 px minimum bitmap size. On the Home board that looked wrong in four ways: a white card sat on the panel-coloured tile, one stray stroke far from the page shrank the whole page to a few pixels and left the frame empty, pen strokes were hairlines, and tiny text turned into overlapping 8 px glyph soup.

## Decision

1. **Background is the panel colour.** `THUMB_BG = (234, 228, 215)` (`#EAE4D7`, DESIGN.md `panel`). The Home board draws every thumbnail tile on `#EAE4D7`, so the `object-fit: contain` bands of the card are invisible. Paper (`#F5F1E8`) is the page behind the cards; a paper thumbnail would be a lighter sheet inside a panel card. The ticket text says "paper-family"; the board is the sign-off reference. If the owner prefers paper, change `THUMB_BG` only and bump `THUMB_REVISION`.
2. **Output 960 x 640** (`CARD_W = 480`, `k = width / 480 = 2`), shown at 480 x 320. Every card-pixel constant below is multiplied by `k`.
3. **Robust fit.** The core box is the 5th to 95th percentile (`TRIM = 0.05`) of all primitive points per axis. A primitive is kept when the centre of its own bounds lies inside the core box padded by `REACH = 0.5` times the larger core side. The fit box is the full bounds of the kept primitives. Scale is `min(k, fit to the frame minus a 16 card px margin)`, so one canvas unit is at most one card px. The rest clip, and a primitive that does not touch the frame is not painted at all. This keeps all near ink and every stroke that is part of the page, and drops only far strays.
4. **Stroke floor.** Lines, shapes and arrows are at least `THUMB_MIN_STROKE = 2` card px; freedraw at least `THUMB_FREEDRAW_MIN = 2.5` card px and its width is multiplied by `FREEDRAW_BOOST = 1.25`. Pressure still widens strokes.
5. **Tiny text is a bar.** Text whose scaled font is under `GREEK_BELOW = 5` card px (10 px at 2x) is drawn as one bar per non-empty line (length 0.5 x font x characters, capped at the box width) instead of glyphs.
6. **Decimation.** Polyline points closer than `THUMB_STEP = 0.8` card px to the last kept point are skipped (the last point is always kept). This keeps the 641-element real-scale fixture under 300 ms.
7. **Cache key.** `THUMB_REVISION = 2` is part of the file name (`thumbs/<id>-r<rev>-<version>.png`) and the ETag (`"r<rev>v<version>"`). `_store` removes any other file of the canvas whose remainder matches `(r<n>-)?<n>`: legacy `<id>-<version>.png` and older revisions go on the next view, and another canvas's file (`a-5`) is never touched. Bump `THUMB_REVISION` whenever the look changes.

`render_crop` is untouched: crops keep the plain style (`CROP_STYLE`, floor 1 px, no boost, no decimation, no bars), so the recognizer inputs of decision 0065 do not change. Drafts and deleted elements are still never drawn (drafts are not content).

This supersedes the thumbnail part of 0065 (480 x 320, white, scale 1.0).

## Consequences

- Far stray ink is clipped from the thumbnail only; chunking, search and export are unaffected.
- A canvas with a large share of its ink far from the rest shows only the main body. The trim is by point count, so a stray with more points than 5 percent of the whole page counts as part of the page.
- The file and ETag formats changed: browsers refetch once, and old cache files are deleted lazily.
- Web code is unchanged: the card already shows the PNG with `object-fit: contain` on the panel colour.
