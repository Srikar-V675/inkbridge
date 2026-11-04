# 0049: Pending and delivered agent ops expire after 24 h

INK-088. Status: accepted.

## Problem

An agent op that no browser ever draws stays `pending` (or `delivered`, if a socket took it and the tab went away) forever. Each one holds a reserved spot in placement and counts against `MAX_OPEN_OPS = 200` per canvas. Once a canvas hits the cap, every `write_text` and `draw_diagram` is refused with a 409 that says only "drafts waiting", so the agent cannot tell how long the blockage has lasted or what would clear it.

## Decision

- `OP_TTL_S = 24 * 3600` in `db/ops.py`. An op whose `created_at` is older than that and whose status is `pending` or `delivered` moves to the existing terminal `expired` state. It never draws and never touches scene elements.
- The sweep is lazy, with no background thread. It runs (a) inside `create_op`, after the op-id idempotency check and before the open-cap count, so an expired op frees its slot in the same transaction; and (b) at the start of `list_ops`, which the REST list and the WebSocket replay both use. Replay therefore skips expired ops without a separate filter.
- `applied` ops are never expired. Their drafts are on the canvas awaiting Accept or Reject, which is the user's decision to make.
- Rows with a NULL `created_at` (from before migration 0004) are never expired.
- The 409 `too_many_open_ops` now also carries `open` (the count) and `since` (the oldest open op's `created_at`). The message names the count, the oldest time and the 24 h expiry, so the agent can tell the user what to do.

## Rejected alternative

- **Background sweeper thread.** It would add a process-lifetime thread and a second writer for a rule that only needs to be true when someone asks. The lazy sweep runs on the two paths where the answer matters (a slot is needed, or a list is served), and it is one indexed UPDATE per call.

## Consequences

- A browser that holds a draft for an op the server has since expired (tab open more than 24 h, op still `delivered`) gets the existing `InvalidTransition` path when it acks. The draft stays unresolved on the canvas. Browser handling of that `op.error` is unchanged (out of scope).
- No `op.updated expired` push goes out on sweep. A browser learns of expiry only on its next fetch or replay.
- `list_ops` now takes a write lock when it runs outside a transaction. Under heavy write contention a GET can wait for the busy timeout. A caller already in a transaction skips the sweep.
- The 24 h constant is a module constant, not an env var, like the other op limits.
