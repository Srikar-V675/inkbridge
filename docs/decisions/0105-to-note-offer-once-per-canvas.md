# 0105: the "Turn this into a note" offer fires once per canvas

Ticket INK-183.

## Cause

`_to_note` anchored to the newest chunk, and `detectors.run` dedupes on `(kind, anchor, key)`. Every new dot became the newest chunk, so every dot raised a new offer. The chip popover for `to_note` only had "Not useful".

## Decision

- `to_note` is deduped on `(kind, key)` only (`_seen_key`): the anchor may move, the offer is raised once per canvas. A dismissed offer stays in the seen set, so it does not return.
- The anchor is the largest chunk by element count (first of equals).
- Tiny chunks never anchor or count toward the 8-chunk threshold, in every detector: a non-connector chunk with fewer than 2 elements and a reading shorter than 2 characters (`MIN_ELEMENTS`, `_tiny`). A one-stroke word read as 2+ characters still counts. A connector chunk is one element by design and is kept. The start values (2 elements, 2 characters) await tuning from logs. `_markup` still sees all chunks.
- The chip popover has a "Copy request" button that copies `Use the inkbridge-export skill to turn canvas "<id>" into a note.` for the user to paste to their agent. The backend never writes the vault. Copying needs a secure origin; on plain HTTP the existing error line shows.

## Out of scope

The `make serve-https` / `.env` item (INK-194).
