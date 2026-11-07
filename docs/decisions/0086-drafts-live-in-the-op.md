# 0086 Drafts live in the op row, not in the scene (INK-114)

Status: accepted. Server only; the web client follows in INK-115.

## Context
A draft was recorded twice: as dashed elements autosaved into the scene, and as an op row with the
element ids the browser acked. The two could disagree. Ops got stuck in `applied` with no elements
(two on `default`), and Accept raced the autosave. Spec v4 (section 3 and the invariants) moves
drafts out of the scene: the one approved change to "drafts are not content".

## Decision
1. **The op row is the only draft record.** Migration 0011 adds `elements_json, box_json, question_id,
   task_id, offer_id, revises, diagram_id, resolved_at` (TEXT, nullable). Status `placed` replaces
   `applied`. Lifecycle: `pending|delivered -> placed -> accepted|rejected`, `accepted -> placed`
   (unaccept), plus `failed` and `expired`. `PATCH /ops/{id}` only sets `failed` and `expired`;
   `update_status` refuses `placed` and `accepted`.
2. **Measure, then place.** The browser sends WS `op.measured {op_id, elements, width, height}`.
   `drafts.measure_op` (one write lock) refuses ids without the op prefix or already in the scene
   (`ExistingElementIds`), re-places with the true size, stores the translated elements with forced
   `customData {author, op_id, draft}` and publishes `op.placed` to every tab. A repeat is a no-op.
   Placement now uses clearance 0: accepted agent ink is excluded from proximity since INK-078, so
   `proximity_threshold` is only used at create time (the estimate). Placed ops reserve their `box_json`.
3. **Accept** (`POST /ops/{id}/accept {dx, dy}`, `|d| <= MAX_OFFSET` 20,000) writes the elements through
   `merge_elements(strict=False)`, the one path allowed to create `<op_id>:` ids (N1 on `POST
   /elements` stays strict). `merge_elements` gained two keyword hooks: `guard(conn)` right after the
   lock and head read (re-checks the op is `placed`, refuses an id already in the scene, tombstones
   included: 409 `id_collision`), and `finish(conn, head)` just before COMMIT (marks the op accepted
   with `{seq, stamps, at}`). A second accept returns the same seq. Reject writes nothing to the scene.
4. **Unaccept** (`POST /ops/{id}/unaccept`, within 60 s) tombstones only elements whose
   `(version, nonce)` still equals the stamp stored at accept; anything the user touched is kept and
   reported in `kept`. The op returns to `placed`.
5. **Migration data step** (`_move_drafts_out_of_scene`): draft rows of accepted ops lose the flag;
   rows of `applied` ops move into the op as `placed` and are tombstoned in the scene (so seq-based clients see the removal); other draft rows are soft-deleted; leftover
   `applied` ops expire. One scene version bump per document that changed; `scenes.element_count` is recounted and chunks are rebuilt with `_sync_chunks` (default chunker settings).

## Skipped on purpose
- `revises` / `superseded` handling and the tether: columns only, no tool sets them.
- `question_id`, `task_id`, `offer_id`, `diagram_id`: stored columns with no writer, not in the API.
- Accept publishes `op.updated` and `chunks.updated` only. `scene.delta` is INK-112's; wire it after
  both merge.

## Consequences
- The web client of this branch cannot draw or resolve drafts until INK-115 (it still acks
  `op.applied`, which the server now answers with an error).
- The `applied` ack, `element_ids` on PATCH and `_check_new_ids` in `update_status` are gone.
- Migration 0011 is one-way: back up the database first.
