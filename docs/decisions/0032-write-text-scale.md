# 0032: write_text and draw_diagram scale to the handwriting (INK-066)

Status: accepted.

Agent text was drawn at Excalidraw's default 20 px, which looks tiny beside tablet handwriting. The server now computes a font size from the stored scene.

1. (Sample rule superseded by 0045.) **Ink scale is the median height of the user's freedraw strokes** (point extents), not the chunk bbox. A chunk bbox height depends on how many lines the paragraph has, so a 10-line paragraph would write 10 times bigger text. The sample is the strokes of the anchor chunk; with no anchor, or fewer than 3 strokes in it (a text or shape chunk), all live strokes on the page. Fewer than 3 strokes overall: the default.
2. (Clamp superseded by 0045.) `font_size = clamp(round(median_height * INK_TO_FONT), MIN_FONT, MAX_FONT)` with `INK_TO_FONT = 1.5`, `DEFAULT_FONT = 28`, `MIN_FONT = 18`, `MAX_FONT = 64` (named constants in `placement.py`). The factor is a first guess to tune on the tablet.
3. `write_text` takes an optional `size` hint (`small`, `normal`, `large`, multipliers 0.75, 1, 1.5, applied before the clamp). `draw_diagram` gets the computed size but no hint, so its tool contract is unchanged.
4. The server stores the result as `payload.font_size` next to `placement`; clients cannot send it (the payload models forbid extra fields). The idempotent-retry comparison excludes it like `placement` and `id_prefix`. Ops stored before this change have none and are treated as 20.
5. Diagrams: the browser passes `themeVariables.fontSize` to Mermaid; the server scales the 600x400 estimate by `font_size / 20` for placement. Mermaid node padding and edge spacing come from the library, so a large diagram at a large font can exceed the estimate; a later op could then overlap it. Accepted.
6. Agent drafts (`customData.draft` or `author: "agent"`) are excluded from the sample so drafts never feed back into scale.
