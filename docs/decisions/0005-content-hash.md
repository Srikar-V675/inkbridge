# 0005: Three hashes, three jobs

Status: accepted (INK-029)

| Hash | Covers | Drives |
|---|---|---|
| `stroke_hash` | Exact ink including ids and absolute position (allow-list unchanged) | `png_stale`: a moved region really needs a fresh crop |
| `content_hash` | Shape of the ink: type, size, angle, points, pressures; no ids, positions as offsets from the elements' bbox origin, deleted elements dropped | Recognition cache key `(region, content_hash, source)`, search index, note provenance |
| `text_hash` | Normalised reading (`text` + `latex`, trimmed, whitespace collapsed) | Early-cutoff staleness in `check_sync` (INK-036) |

- Moving a chunk or redrawing identical ink changes `stroke_hash` only: no new recognition, no stale note,
  but the crop is flagged stale.
- Offsets are rounded to 0.001 px before hashing so float noise from translation does not change the hash
  (an offset landing within ~1e-13 of a 0.0005 rounding boundary could still flip; the cost is one extra
  recognition, never a wrong reading);
  rows are sorted by rounded offset then content, so draw order and ids never matter.
- Integral floats are hashed as ints at any depth (INK-031): browser JSON gives `15`, but after a 0.25 px
  drag the offset is computed as `15.0`, which used to change the hash on a pure move. On start-up
  `db._rekey_integral_hashes` moves any region whose stored hash is the old form of its current ink (and
  its readings and search row) to the new form, so nothing is re-read. `stroke_hash` is unchanged
  (re-keying it would flag every crop stale for nothing).
- Text elements also hash `text`, `fontSize` and `fontFamily` (a fixed-width text edit changes no geometry).
- `version`, `versionNonce`, `updated`, `seed` and `customData` are never hashed.
- Migration 0004 re-keys `recognitions` to `content_hash` (table rebuild). `db._backfill_v2` moves a reading
  whose old key equalled its region's current `stroke_hash` to the current `content_hash`; older readings keep
  a key that never matches. It also fills `regions.content_hash` and `recognitions.text_hash`, and `init_db` reruns it whenever a region still has no `content_hash` (a crash between recording the schema version and the backfill heals on next start).
- Points stay relative to each element's own `x,y` anchor, as Excalidraw stores them. Re-anchoring identical
  ink (shifting `x` and every point the other way) changes the hash; Excalidraw does not do this on a move, and
  a redrawn freedraw stroke always starts at `[0, 0]`, so the cost is at most one extra recognition.
- `_backfill_v2` uses the live `content_hash`. If the algorithm ever changes, existing keys need an explicit
  re-key migration (the start-up heal only fills `NULL` hashes).
- These points refine tech ref 4.4 (which hashes exact offsets and no text fields) and take precedence over it.
