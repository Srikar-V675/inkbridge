# 0011: Chunk identity, orphaning and change detection

Status: accepted (INK-031). Refines tech ref 5.6 to 5.8 and gap 7.

- **Rows.** Chunks are `regions` rows with `created_by='auto'`, written inside `put_scene`'s
  transaction (now `BEGIN IMMEDIATE`, rolled back on any error). Anything else is a manual region:
  the chunker never selects, adopts or orphans it, and `POST /documents/{id}/regions` rejects
  `created_by=auto` so a client cannot hand a manual region to the chunker.
- **Matching** (`chunker.match_chunks`, pure). Candidates are all auto chunks of the canvas, orphaned
  ones included. Greedy one-to-one over pairs with element-id Jaccard above
  `ChunkerConfig.match_threshold` (0.5), highest J first; ties go to the larger overlap, then active
  before orphaned, then ids, so the result is deterministic.
- **Orphaning.** An active chunk left unmatched becomes `orphaned`. It keeps its last element ids,
  bbox and hashes (so undo can match it again and a note's provenance still compares), and
  `successor_of` is set once, at that moment: the cluster sharing the most elements, tie the one
  higher on the page (bbox top), else NULL (everything deleted). Reactivation clears `successor_of`.
  A successor that is later orphaned in turn forms the chain the stale banner follows.
- **Change detection.** `put_scene` diffs the previous and new element lists by id and whole-element
  equality, which covers id + version and stays correct for clients that do not bump `version`.
  Manual regions are refreshed only when they hold a changed id; a chunk whose element set is
  unchanged and holds no changed element is skipped without hashing. Clustering itself still runs on
  the whole scene (2,000 elements cluster in about 15 ms; a one-stroke save takes about 25 ms).
- **Invalidation.** `stroke_hash` changed: `png_stale=1`. `content_hash` changed: the FTS row is
  rebuilt for the new hash (normally dropped; restored when undo brings back ink that has a reading)
  and `kind` is re-hinted. A new chunk starts `png_stale=1` with `png_path` set to
  `data/crops/<id>.png`, written later by the browser (INK-057); the image route creates the folder.
- **Listing.** `GET /documents/{id}/regions` (and the MCP `list_regions` tool behind it) keeps listing
  manual regions only; `?chunks=true` lists chunks until INK-033 adds the chunks API. `GET /regions/{id}`
  serves both and now includes `successor_of`.
- **Small-chunk weakness, not fixed.** A 2-element chunk gaining 3 elements has J = 0.4 and gets a new
  id (the old one is orphaned with the new one as successor). The alternative for INK-038 to switch to
  if real pages need it: keep the id when the old set holds at least 60% of the new one or the new set
  holds at least 60% of the old one (containment instead of Jaccard). Only `match_chunks` changes.
