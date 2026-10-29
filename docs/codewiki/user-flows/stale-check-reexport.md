# Stale check and re-export

**Story:** as a note-taker, I want to know which blocks of my note are out of date after I edit the canvas, and update only those.

1. The skill reads `inkbridge.chunks` from the note frontmatter and calls `check_sync(chunks:[{id, hash, reading}], wait_s)` (`POST /documents/{id}/check_sync`).
2. The API compares `content_hash` first, then the reading hash:
   - Same content hash: `fresh` (a move counts as fresh).
   - Different content hash, same reading after re-read: `fresh_after_reread` (cosmetic edit).
   - Different reading: `changed`.
   - Chunk replaced by a split/merge: `replaced` with `successor`.
   - Gone: `removed`. Not in the note yet: `new`.
3. Chunks needing a new reading are read by the recognition worker while the call waits (bounded by `wait_s`, only for opted-in canvases). `changed` with `reading: null` means no reading arrived in time.
4. The skill rewrites only changed blocks (and their crop embeds); several `replaced` entries can share one `successor`, so rewrite that block once.

Decision 0020. Test: `server/tests/test_check_sync.py`, `test_vault_export.py`.
