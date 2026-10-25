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
- **Ack ids must be new.** `PATCH /ops/{id} {status: applied, element_ids}` succeeds only if each
  id is absent from the stored scene, or present only as an element tagged
  `customData {author: "agent", op_id: <this op>}` (autosave may persist the drafts before the
  ack arrives), and no other op has recorded it. This matters because Reject removes exactly
  the op's recorded ids: a user element recorded here would be deleted by a Reject.
- **Placement is computed by the server at enqueue time** and stored as `payload.placement {x, y}`
  (top-left). Right of the anchor chunk's box (gap 40 px), else below it, else below the lowest
  occupied box at the left edge of the content, or the origin on an empty canvas. Occupied boxes
  are the live (non-deleted) scene elements plus the reserved spots of ops still pending,
  delivered or applied, so stacked writes do not land on each other. Sizes are estimates: text at
  20 px (0.6 em per character, 1.25 em per line); a diagram reserves 600 x 400. A diagram larger
  than that placed beside an anchor could still overlap; "below everything" cannot, whatever the
  size. The browser (INK-042/044) may refine the position after layout.
- **Lifecycle** `pending -> delivered -> applied -> accepted | rejected`, with `failed` and
  `expired` from pending or delivered. `delivered` is set by the server when it pushes the op
  (`mark_delivered`, INK-042), not by `PATCH`. Repeating the current status is a no-op (an
  `applied` repeat must carry the same ids); any other move is `409 invalid_transition`.
- **Idempotency.** A client may send `op_id`; posting the same id with the same body returns the
  existing op (200), a different body is `409 op_id_conflict`.
- **No new migration.** `agent_ops` already has every column (0001 + 0004); statuses are enforced
  in code rather than with a CHECK, which would need a table rebuild.
