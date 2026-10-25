# 0013: Arrow merge, links and connector attachment

Status: accepted (INK-032). Refines tech ref 5.5. Code: `chunker.chunk_scene` (pure), `db._sync_chunks`.

- **Ends.** A bound end (`startBinding` / `endBinding`) maps to the chunk holding the bound element. When
  that element is in no chunk (deleted, a draft, another arrow) the end falls back to its point, as a
  free end does: `x + points[0]` / `x + points[-1]` (with `y` likewise), mapped to the nearest chunk whose
  box is within `link_reach * median` (ties: the chunk first in id order). Otherwise it dangles.
- **Length** is the arrow's polyline length (what was drawn), not the straight start-to-end distance.
  At most `arrow_merge * median` with both ends mapped: the two chunks merge (transitively). Otherwise a
  link `(from = start chunk, to = end chunk, 'arrow')`. Links are directed and deduplicated; an arrow whose
  ends land in the same final chunk (directly or through another merge) makes no link.
- **Attachment.** Every live arrow joins the final chunk of its start, else of its end; an arrow with both
  ends dangling forms a chunk of its own, so no live ink is outside every chunk. Its bound label
  (`containerId` = arrow) goes with it; deleted or draft arrows take their labels out with them.
- **Lines** are attached the same way but never merge or link: an underline or a divider should not
  join or connect ideas.
- **Rebuild.** `links` rows for the document are deleted and re-inserted on every scene save inside the
  chunk transaction, after ids are assigned, so they only ever name current (active) chunks. `near` stays
  reserved. `db.list_links` reads them; the HTTP and MCP surfaces arrive with INK-033 / INK-034.
- **Config.** `arrow_merge` (6) and `link_reach` (3) are now used; `ChunkerConfig` rejects
  non-positive `k`, `arrow_merge`, `link_reach`, `min_median` and a `match_threshold` outside [0, 1).
- **Cost.** End mapping is arrows x chunks box distance tests, fine for hundreds of chunks; index the
  boxes in a grid if real canvases need it.
