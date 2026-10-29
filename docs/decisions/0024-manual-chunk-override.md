# 0024: Manual chunk merge and split are pinned chunks

Status: accepted (INK-059). Refines 0004 ("a manual region wins over an automatic chunk") and 0011.
Code: `chunker.pin_groups` / `chunk_scene(pins=)`, `db.merge_chunks` / `db.split_chunk`,
`api/overrides.py`, `web/src/overrides.ts`.

- **A pin, not a `created_by='user'` row.** The override is the chunk row itself with `pinned = 1`
  (migration 0005); it stays `created_by='auto'`. A separate manual region on the same elements
  would duplicate the ink under two ids and drop out of everything that reads chunks (listing, deep
  links, crop sync, export, `match_chunks`). "Manual wins" is kept as a rule: the pin is the user's
  grouping and later chunker runs never change it. Manual regions (`created_by='user'`) stay focus
  regions and never constrain the chunker.
- **Semantics: a pinned chunk is a hard boundary.** Its ink (the row's element ids that still
  cluster: live, not a draft, not an arrow or line) forms exactly one chunk. Nothing joins it by
  proximity, and an arrow merge into it becomes a link. Arrows and lines still attach to it by the
  0013 rules, and bound text always follows its container. New strokes written right next to a pinned
  chunk start a chunk of their own; select both and merge to add them. This makes the result
  predictable, and the test "a later automatic run does not undo the override" holds for any edit.
  Pinned ink is left out of the proximity pass but still counts in the median, so pinning one group
  does not change how the rest of the page clusters.
- **Merge** (`POST /documents/{id}/chunks/merge {chunk_ids}`, at least 2 active chunks): one new
  pinned chunk holds their union. **Split** (`POST .../chunks/split {chunk_id, element_ids}`): two new
  pinned chunks, the selection (plus bound text) and the rest of the chunk. Both parts are pinned, so
  the result is exactly two chunks and stays that way. Only ink decides a split. Arrows and lines in
  the selection follow the chunk their start lands in, and the response gives the real membership.
  Picking a bound label also picks its container (they are one unit). A split selection with no ink
  of its own, or one that leaves nothing behind, is refused (422). So is a merge that includes a
  chunk of nothing but connectors (a dangling arrow's own chunk), because it has no ink to pin. The web
  client ignores connectors when it decides what to offer, so it never proposes either.
- **Ids and successors.** The new rows are inserted, the originals are unpinned, and the chunker
  re-runs on the stored scene in the same `BEGIN IMMEDIATE` transaction. The new rows match their
  clusters with Jaccard 1, so they keep their ids. The originals are left unmatched and are orphaned
  with `successor_of` pointing at the cluster that took most of their ink: the merged chunk, or the
  larger half of a split. A deep link or note to an original therefore follows like any other split
  or merge. The transaction rolls back if the new ids are not active or an original is not orphaned
  afterwards.
- **Errors.** 404 for an unknown canvas, an unknown id, a manual region or another canvas's chunk.
  409 for an orphaned chunk (the caller's list is stale). 422 for a bad request shape or a selection
  as above. A refused override changes no row (tested).
- **Ink is never touched.** Overrides read the scene and write only `regions` and `links`. The scene
  version and JSON stay byte-identical (`test_overrides_never_modify_or_delete_elements`), so the
  browser's next save on the same `base_version` still succeeds.
- **Pins end with their ink.** An orphaned row is unpinned. Erasing all of a pinned chunk's ink
  removes the constraint; undo then brings the ink back as an ordinary auto chunk. There is no
  "unpin" action yet: merge or split again to change the grouping.
- **Web.** With the chunk overlay on, "Merge chunks" is enabled when the selection touches two or
  more chunks (whole chunks merge), and "Split selection" when it covers part of one chunk. Selected
  ids in no chunk (drafts, ink not saved yet) are ignored. Pinned chunks are labelled "manual".
- **E5.** Pinned chunks are counted with `SELECT count(*) FROM regions WHERE pinned = 1`.
