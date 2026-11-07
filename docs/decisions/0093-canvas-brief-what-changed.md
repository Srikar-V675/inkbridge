# 0093: Canvas brief and what_changed (INK-135)

## Context
A cold agent session knows nothing about a canvas: what it is for, or what the user did since it last looked.

## Decision
- Table `canvas_memory` (migration 0014): one row per canvas with `brief_md` and `last_seen_seq`. The brief lives in SQLite and never goes to the vault. Capped at 4000 chars (422 beyond, never truncated).
- A chunk changed since N when any of its `element_ids` has a `scene_elements` row with `seq > N` (deletions included). Active such chunks are `changed`; an orphaned chunk with no successor is `removed`; an orphan with a successor is not listed (the successor is). No `regions.seq` column: element seq already says it.
- A reading arriving later does not move `seq`, so it is not a change. `what_changed` answers "what did the user do to the ink"; `read_canvas` and `check_sync` carry reading state.
- `mark_seen` is false by default so a peek never moves the cursor. `GET .../changes?mark_seen=true` mutates, but only the agent's own bookmark, never scene elements.
- Tools `what_changed` and `set_canvas_brief`; `read_canvas` returns the brief; the server instructions tell an agent to call `what_changed` first.

## Consequences
- A moved but unedited chunk counts as changed. Early cutoff on text is `check_sync`'s job.
- One cursor per canvas: two agents sharing a canvas share it unless they pass `since`.
- Migration number 0014 leaves no gap at the time of writing.
