# 0009: Agent ops queue: what "only adds" means on the server

Status: accepted (INK-041)

Invariant N1 (an agent never edits or deletes your ink) is held by the API, because the browser
is not a trusted enforcement point. Code: `server/src/inkbridge/db/ops.py`, `api/ops.py`.

- **Two op types only.** `write_text {text, anchor?}` and `draw_diagram {mermaid, anchor?}`.
  Any other type (delete, update, edit, ...) is a 422, and each payload schema forbids extra
  fields, so there is no way to express an edit.
- **Existing-id guard runs on the raw payload, before the schema.** Every string anywhere in the
  payload (keys included) is compared with every element id in the stored scene, deleted
  elements included. A match is `422 {code: "existing_element_id", ids}`. Running it before the
  schema means the refusal does not depend on which field carries the id, and it is repeated
  under the write lock in `create_op`. Element ids are random, so ordinary text does not collide;
  text that happens to equal an id is refused, which is the safe side.
- **Ack ids must be ids issued for the op.** Every op carries `payload.id_prefix` (`<op_id>:`);
  op ids cannot contain `:`, so no op's prefix is a prefix of another's, and enqueue refuses a
  client-chosen `op_id` whose prefix some scene element already has. The browser must give every
  element it creates for the op an id starting with that prefix (INK-042/044 rewrite Mermaid ids
  and their references). `PATCH /ops/{id} {status: applied, element_ids}` refuses any id without
  the prefix with `422 existing_element_id`, whether or not it is in the stored scene. Prefixed
  ids already in the scene are this op's own drafts (autosave can store them before the ack).
  This matters because Reject removes exactly the op's recorded ids: a user element recorded here
  would be deleted by a Reject. An earlier draft trusted `customData {author, op_id}` tags, but
  any client writes customData (and Excalidraw copies it on duplicate), so a tag proves nothing.
- **Placement is computed by the server at enqueue time** and stored as `payload.placement {x, y}`
  (top-left). Right of the anchor chunk's box (gap 40 px), else below it, else below the lowest
  occupied box at the left edge of the content, or the origin on an empty canvas. Occupied boxes
  are the live (non-deleted) scene elements plus the reserved spots of ops still pending,
  delivered or applied, so stacked writes do not land on each other. Sizes are estimates: text at
  20 px (0.6 em per character, 1.25 em per line); a diagram reserves 600 x 400. A diagram larger
  than that placed beside an anchor could still overlap; "below everything" cannot, whatever the
  size. The browser (INK-042/044) may refine the position after layout. Placement only sees the
  stored scene, so ink drawn in the seconds before the next autosave is invisible to it; the
  browser should flush its pending save when an op arrives (INK-042).
- **Lifecycle** `pending -> delivered -> applied -> accepted | rejected`, with `failed` and
  `expired` from pending or delivered. `delivered` is set by the server when it pushes the op
  (`mark_delivered`, INK-042), not by `PATCH`. Repeating the current status is a no-op (an
  `applied` repeat must carry the same ids); any other move is `409 invalid_transition`.
- **Replay.** A reconnecting browser asks for `?status=pending,delivered`: an op pushed to a
  browser that went away before acking stays `delivered` and must be offered again. Delivered ops
  that never complete keep reserving their spot until the waiting tool marks them `expired`.
- **Idempotency.** A client may send `op_id`; posting the same id with the same body returns the
  existing op (200) before any other check, a different body is `409 op_id_conflict`.
- **No caller identity.** `PATCH` cannot tell the browser from the user (the API has no auth on
  the LAN), so either can set any allowed status; the lifecycle, not the caller, is enforced.
- **No new migration.** `agent_ops` already has every column (0001 + 0004); statuses are enforced
  in code rather than with a CHECK, which would need a table rebuild.
