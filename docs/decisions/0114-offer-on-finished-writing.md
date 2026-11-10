# 0114: Offers on finished writing only (INK-199)

Status: accepted. Follows 0089, 0091, 0095, 0112.

## Why

Owner test, 10 Nov 08:26-08:31: four tapped `question` offers landed on four chunk ids (6561b2e3, c6ea7380, 24cb9bc4, ba44691a) for one line being written. Three of the four were `orphaned` with `successor_of` NULL (the chunker re-clustered the line and the Jaccard match failed); only c6ea7380 -> ba44691a had a successor. Two ops ended `rejected`, two `placed`. The offer fired on half-written ink, the agent answered the partial reading, and the line then changed id under the draft.

## The four rules

1. **Stability gate** (`agent/detectors.py`). A question or open-equation offer needs the chunk's `updated_at` at least `STABLE_S` (2.0 s) old, and a question also needs a finished reading (`_complete`: ends in `?` or `=`, or two or more words). `held_unstable` tells `api/offers.scan_now` that a candidate was held, and `scan_now` re-arms itself through the 2 s debounce, so a chunk that becomes stable is found on the next scan and the loop ends.
2. **One tapped offer per line** (`detectors.run`). A candidate is skipped (`held=answer_pending`) while a tapped offer on the same line has a pending or running task. "Same line" is `supersede.line_of`: the chunk itself when active, else its replacement.
3. **Supersede** (`db/supersede.py`, run first in `scan_now`). When an anchor chunk is replaced, its open offers expire, `placed` drafts are rejected with `error='superseded'`, and `pending`/`delivered` ops expire with the same error. `accepted` ops are never touched. Both updates are published (`offer.updated`, `op.updated`). A replacement is the `successor_of` chain, else an active reader-written chunk whose box covers at least `OVERLAP` (0.5, intersection over the smaller box) of the orphan. An orphan with no cover (ink deleted) keeps its offer.
4. **Fresh anchor at claim** (`db/tasks.claim` -> `refresh_anchor`). The task input gets the live `anchor_chunk` and its current `anchor_reading`, so the agent answers the final reading, not what the offer saw. The runner prompt carries the reading inside `untrusted_data`; with no reading yet it says to call `get_region` and wait.

Start values are hypotheses: `STABLE_S` 2.0, `OVERLAP` 0.5.

## Why supersede lives in `scan_now`

Not in the scene save (`_sync_chunks`): `scan_now` runs after the debounce on its own connection and already publishes, so the save path and its invariants stay untouched. The cost is up to 2 s before a replaced chunk's offer expires.

## Choices

- A placed draft whose chunk was replaced is rejected even when no newer draft exists. A replaced id means a real re-cluster, not a stray stroke; the new reading gets its own offer.
- Accepted ops are never touched (user-visible ink stays).
- Agent drafts never become the replacement (`source != "agent"`).

## Shortcuts

- No worker wait at claim: if the live chunk has no reading yet, the prompt says so.
- The overlap fallback can join two nearby but different ideas written on top of each other.
- The unstable hold re-arms through the 2 s debounce only; there is no timer of its own.

## Tests

`tests/test_detectors.py` (gate, completeness, re-arm), `tests/test_supersede.py`, `tests/test_agent_tasks.py` (claim follows the anchor and carries the reading), `tests/test_ask_runner.py` (prompt).
