# 0018: read_canvas response limits

Status: accepted (INK-034). Extends [0003](0003-agent-output-limits.md) to the whole-canvas read.

- **Outline cap.** The JSON text of `read_canvas` never exceeds 60,000 characters (about 15k tokens),
  written compactly (no indentation) because it is read by a model, not a person. Chunks are kept in
  reading order until the next would cross the cap; the rest are counted in `omitted` and the `note`
  names the `offset` to call again with. `chunk_count` is always the canvas total, so the model knows
  the outline is partial. Cutting at a chunk boundary keeps every shown chunk whole.
- **Readings.** A single `text` or `latex` over 4,000 characters is shortened with an ellipsis and flagged
  `text_truncated` / `latex_truncated`, so one runaway reading cannot push every other chunk out;
  `get_region` still returns it in full.
- **Overview.** One PNG at most 1024 px wide (the 0003 image cap), from `GET /documents/{id}/overview`,
  which also caps the area at 16 Mpx. If it fails, the outline still arrives with a text note giving the
  cause, as `get_region` does for a missing crop.
- **Fields** are the outline subset of `GET /documents/{id}/chunks` named by the ticket; element ids,
  hashes other than `content_hash` and orphaned chunks are left out (they cost tokens and do not help
  reading). An unknown canvas is a tool error that says to check `document_id`.
- **Scope.** `search` takes `document_id` (default `INKBRIDGE_DOCUMENT`); `list_regions` keeps listing
  saved regions only, and `get_region` reads chunk ids as well.
