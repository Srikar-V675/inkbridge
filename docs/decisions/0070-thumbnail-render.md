# 0070: Canvas thumbnails that look right (INK-171)

Status: accepted. Owner checks pending: look at the thumbnails of the real canvases at card size on the tablet; confirm the panel-colour background.

## Context

The first thumbnails (INK-120 / INK-118, decision 0065) were 480 x 320 on white, scaled by at most 1.0 to the bounding box of every drawable element, strokes floored at 1 px and text drawn with an 8 px minimum bitmap size. On the Home board that looked wrong in four ways: a white card sat on the panel-coloured tile, one stray stroke far from the page shrank the whole page to a few pixels and left the frame empty, pen strokes were hairlines, and tiny text turned into overlapping 8 px glyph soup.

## Decision

1. **Background is the panel colour.** `THUMB_BG = (234, 228, 215)` (`#EAE4D7`, DESIGN.md `panel`). The Home board draws every thumbnail tile on `#EAE4D7`, so the `object-fit: contain` bands of the card are invisible. Paper (`#F5F1E8`) is the page behind the cards; a paper thumbnail would be a lighter sheet inside a panel card. The ticket text says "paper-family"; the board is the sign-off reference. If the owner prefers paper, change `THUMB_BG` only and bump `THUMB_REVISION`.
2. **Output 960 x 640** (`CARD_W = 480`, `k = width / 480 = 2`), shown at 480 x 320. Every card-pixel constant below is multiplied by `k`.
3. **Robust fit.** A primitive counts as part of the page when its centre is within `REACH = 6` times `max(MAD, median primitive size)` of the median centre on both axes (MAD = median distance of the centres from their median). Primitives outside that reach are dropped only when they are strays: together at most `max(STRAY_FLOOR = 2, STRAY_SHARE = 10 percent of all primitives)`. If more than that are far away they are a real second cluster and the fit covers all ink. Example: against a main cluster of 48 elements, a group of 5 or fewer far elements is a stray (10 percent of 53 primitives is 5) and clips, while a second cluster of 6 elements or more (a 6-element one is 11 percent of 54) stays in the thumbnail, and a lone stray beside a 7-element sketch (the floor of 2) still drops. Only the primitive count is used; ink area or length is not weighed. The fit box is the full bounds of the kept primitives. Scale is `min(k, fit to the frame minus a 16 card px margin)`, so one canvas unit is at most one card px. The rest clip, and a primitive that does not touch the frame is not painted at all. This keeps all near ink and every stroke that is part of the page, and drops only far strays. The first design (5th to 95th percentile of points plus a reach pad) was tried and dropped: it counts points, so on a sparse sketch a 10-point stray stroke is more than 5 percent of the points and still shrank the page to two dots (found in the browser check). The MAD rule counts primitives and works at any element count.
4. **Stroke floor.** Lines, shapes and arrows are at least `THUMB_MIN_STROKE = 2` card px; freedraw at least `THUMB_FREEDRAW_MIN = 2.5` card px and its width is multiplied by `FREEDRAW_BOOST = 1.25`. Pressure still widens strokes.
5. **Tiny text is a bar.** Text whose scaled font is under `GREEK_BELOW = 5` card px (10 px at 2x) is drawn as one bar per non-empty line (length 0.5 x font x characters, capped at the box width) instead of glyphs.
6. **Decimation.** Polyline points closer than `THUMB_STEP = 0.8` card px to the last kept point are skipped (the last point is always kept). This keeps the 641-element real-scale fixture under 300 ms.
7. **Cache key.** `THUMB_REVISION = 2` is part of the file name (`thumbs/<id>.r<rev>.<version>.png`) and the ETag (`"r<rev>v<version>"`). Canvas ids are `[A-Za-z0-9_-]`, so the `.` separator cannot occur in an id and `<id>.r<rev>.<version>.png` cannot collide with another canvas's file whatever its id ends in (an infix like `-r2-` could). `_store` removes the files of this canvas only, matched as a whole name `<id>(.r<n>.<n>|-<n>).png`: older revisions and the pre-0070 legacy `<id>-<version>.png` go on the next view, and another canvas's file (`a-5`, `x-r2`) is never touched. Bump `THUMB_REVISION` whenever the look changes.

`render_crop` is untouched: crops keep the plain style (`CROP_STYLE`, floor 1 px, no boost, no decimation, no bars), so the recognizer inputs of decision 0065 do not change. Drafts and deleted elements are still never drawn (drafts are not content). Primitives with a non-finite point (for example a NaN angle, which the element check does not catch) are dropped in `_prims`, so they cannot disturb the fit or reach PIL.

This supersedes the thumbnail part of 0065 (480 x 320, white, scale 1.0).

## Consequences

- Far stray ink is clipped from the thumbnail only; chunking, search and export are unaffected.
- Far ink of at most 10 percent of the primitives (or two primitives) is clipped; a larger far group is drawn and the page shrinks to fit it. A stray within six median spreads of the centre of the page counts as part of the page. A page whose ink is a few big strokes plus many tiny far marks can keep the marks, since only counts are compared.
- The file and ETag formats changed: browsers refetch once, and old cache files are deleted lazily.
- Web code is unchanged: the card already shows the PNG with `object-fit: contain` on the panel colour.
