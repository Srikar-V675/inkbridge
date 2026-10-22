# 0005: Three hashes, three jobs

Status: accepted (INK-029)

| Hash | Covers | Drives |
|---|---|---|
| `stroke_hash` | Exact ink including ids and absolute position (allow-list unchanged) | `png_stale`: a moved region really needs a fresh crop |
| `content_hash` | Shape of the ink: type, size, angle, points, pressures; no ids, positions as offsets from the elements' bbox origin, deleted elements dropped | Recognition cache key `(region, content_hash, source)`, search index, note provenance |
| `text_hash` | Normalised reading (`text` + `latex`, trimmed, whitespace collapsed) | Early-cutoff staleness in `check_sync` (INK-036) |

- Moving a chunk or redrawing identical ink changes `stroke_hash` only: no new recognition, no stale note,
  but the crop is flagged stale.
- Offsets are rounded to 0.001 px before hashing so float noise from translation cannot change the hash;
  rows are sorted by rounded offset then content, so draw order and ids never matter.
- Text elements also hash `text`, `fontSize` and `fontFamily` (a fixed-width text edit changes no geometry).
- `version`, `versionNonce`, `updated`, `seed` and `customData` are never hashed.
- Migration 0004 re-keys `recognitions` to `content_hash` (table rebuild). `db._backfill_v2` moves a reading
  whose old key equalled its region's current `stroke_hash` to the current `content_hash`; older readings keep
  a key that never matches. It also fills `regions.content_hash` and `recognitions.text_hash`, and `init_db` reruns it whenever a region still has no `content_hash` (a crash between recording the schema version and the backfill heals on next start).
