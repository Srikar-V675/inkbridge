# 0116: Drafts answer in place (INK-201)

Status: accepted. Supersedes the placement order of 0047 and 0094 (the rings stay as the fallback).

## Evidence
On the owner's canvas an answer to an anchored question landed 1250 px above it, and another sat to the
right and below, never under its question. `place` scored rings E, SE, S, ... by distance, so any free
spot nearest the anchor won, and a large estimated box (long text, font 50 to 100) ruled the below spot out.

## Decision
- **Flow order** when an anchor exists: (1) directly below, left-aligned (`x = anchor.x`,
  `y = anchor.bottom + gap_for(fs)`), (2) directly right (`x = anchor.right + gap`, `y = anchor.y`),
  (3) the existing candidate search. A flow spot is taken only if clear of all occupied boxes, open
  drafts included, so two questions never collide. No newest-draft column alignment applies to flow spots.
- **The arrow is made by the server** in `measure_op`, where the true size is known: one dashed arrow
  element `<prefix>flow-arrow`, tagged `customData {author, op_id, draft}` through `_as_draft`. It is
  part of the op, so it is accepted, rejected and unaccepted with it, and the existing id-prefix and
  new-id checks cover it (agent paths still only add elements with the op prefix). Only for the below
  and right cases; a client that sent its own `flow-arrow` id gets no second arrow. It is not bound:
  dragging only the text leaves it behind.
- **"Answer:" lead**: `write_text` with a `question_id` gets `Answer: ` prepended unless the text
  already starts with it (case-insensitive). Done in `api/ops._enqueue` before placement estimates size.
- **Web**: `Tether` draws nothing when the op has its own flow arrow (the tether stays as the fallback
  for ring placements); `offsetOf` ignores the arrow so it never reads as a drag.
- **Chunker (v1)**: an accepted agent arrow belongs to its op's group instead of joining the chunk at its
  start, so the question's chunk keeps its ink and hash and never merges with the answer's. v2 already
  keeps native arrows out of chunk members.

## Consequences
Placement tests that assumed east-first now assert below first, then right. Rings, view scoring and
connector penalties apply only after both flow spots are blocked.
