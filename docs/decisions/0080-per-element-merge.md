# 0080 Saves merge element by element (INK-111, closes INK-090)

Status: accepted. Two-device check on the LAN pending (owner).

## Context
A save used to be a whole-scene write guarded by a version lock (`base_version`, 409 on a mismatch,
decisions 0008 and 0040). Two devices on one canvas took turns losing: the second one got a 409, reloaded
and merged in the browser. INK-090 showed the browser merge could still drop an edit on a version tie.
INK-110 (0077) moved the scene to one row per element, which makes the natural unit of a save one
element. This ticket drops the lock and merges on the server, under the write lock, with one rule that
the web client shares.

## Decision
1. **Merge, not lock.** Neither `PUT /scene` nor `POST /elements` has a version lock. `PUT /scene` never
   answers 409 (the 409 code in `sceneSync.ts` stays as dead code; INK-113 deletes it with the
   single-flight sender). `SceneIn.base_version` stays required so old tabs still validate.
2. **`PUT /scene` merges what it sends; it never replaces.** A full PUT that omits an id deletes
   nothing: omission is no evidence of deletion, only `isDeleted: true` at a higher version deletes. This
   supersedes the "a full PUT hard-deletes omitted live ids" rule of 0077. `delta` is accepted and
   ignored (a full list and a delta are the same merge; supersedes the flag of 0036).
3. **The head bumps only when a row changed.** A batch that changes nothing returns the current head and
   does not refresh regions, run the chunker, publish `chunks.updated` or read the scene. This replaces
   0077's "every save bumps the version by 1".
4. **The rule** (`db.elements.wins`, `web/src/sync/mergeRule.ts#winsOver`): the higher `version` wins; on
   equal versions the lower `versionNonce` wins (Excalidraw's own reconcile); equal version and equal
   nonce keeps the stored row. A missing or non-numeric version or nonce counts as 0. There is no
   fallback. An incoming element with the same `(version, nonce)` as the stored row is neither written
   nor returned in `newer`. The one corner: equal version and nonce with different content keeps the
   stored row (it cannot happen with Excalidraw, which gives every edit a new version).
5. **N1 (drafts never enter the scene) is enforced on `POST /elements` only for now.** Until INK-114 and
   INK-115 move drafts out of the scene, the web client stores agent drafts (`customData.draft`, ids
   `<op_id>:...`) in the scene through `PUT /scene`; refusing them there would 422 every autosave while a
   draft is on the canvas. So `merge_elements(..., strict=)` takes a flag: `POST /elements` passes `True`,
   the legacy `PUT /scene` passes `False` (marked `INK-114: drop this flag`). A deliberate narrowing of the
   ticket's "reject" for the legacy route.
6. **N1 details** (`elements.n1_violations`): an element with `customData.draft` truthy is refused even if
   its row exists; a **new** id (no row, tombstone stubs count as rows) containing `:` is refused (op ids
   never contain `:`, Excalidraw ids never do, so no table lookup is needed); one refused element refuses
   the whole batch with 422 `{"detail": {"refused": [ids], "reason": ...}}`, nothing is stored and the
   idempotency key is not recorded.
7. **`newer`.** The stored row (parsed JSON) of each sent element that lost to a strictly different
   `(version, nonce)`. `PUT /scene` also puts in it every row with `seq > base_version` whose id the
   request did not send, so a stale tab learns what the other device wrote (this replaces the old 409
   reload). A shrunk tombstone comes back as the stub `{id, version, versionNonce, isDeleted: true}`.
8. **Idempotency** by `(device, batch)`: key `"{device}:{batch}"` in the existing in-memory
   `db.scenes._applied` (cap 256, lost on restart; a replayed batch is harmless because merging is
   idempotent). `X-Inkbridge-Save: tab:seq` on `PUT` maps to the same key, so the header keeps working and
   0040's store is reused. A replay returns the original `seq`, `newer: []`, and applies and publishes
   nothing. The `last_writer` part of 0040 (the 409 body naming the other tab) is gone.
9. **Web.** The client stays on `PUT /scene` in this ticket. Moving the sender to `POST /elements`
   (journal, overlapping batches, timeout, a stored `device` id) is INK-113; live push is INK-112. In
   scope here: the shared rule table and applying `newer` from a PUT answer (`applyNewer`): without a 409 a
   stale tab would otherwise keep ink the server has overridden, or never learn another device's strokes.
   The answer reloads the canvas with the merged list and raises no "conflict" state; edits made during
   the request stay pending.
10. **Shared rule table**: `server/tests/data/merge_rules.json`, rows of `{name, incoming, current, wins}`
    (nonce may be `null`). `server/tests/test_merge_rule.py` and `web/tests/mergeRule.test.ts` both load
    it, so a new row tests both sides. This is the INK-090 closing test.

## Routes
- `POST /documents/{id}/elements` `{device, batch, elements}` -> `{seq, newer, timing}`; 422 on N1, NaN,
  bad geometry, a bad `device` (`[A-Za-z0-9_-]{1,64}`), a negative `batch` or over `MAX_ELEMENTS` rows;
  404 unknown canvas. Publishes `chunks.updated` once, only if a row changed.
- `PUT /documents/{id}/scene` -> `{version, seq, newer, timing}`, same merge with `strict=False`.
- `db.merge_elements(conn, doc, elements, *, key, base_seq, strict, ...)` -> `MergeResult(seq, newer,
  changed, replay)`; `db.put_scene` stays as a wrapper for the outline code, tests and scripts.

## Consequences
- Edits must raise `version` to win. Excalidraw always does; tests that edited an element in place now bump
  it (the `Scene.put` helper in `tests/test_region_staleness.py` does it, and sends elements a test dropped
  as deleted copies).
- `VersionConflict`, `_apply_delta`, `remove_rows` and the API's `_last_writer` are removed.
- A stale tab sees another device's ink only through `newer` on its next save, or on reload, until
  INK-112 (live push). `since` plus `POST /elements` clients arrive with INK-113.
- A merge that changes anything still parses every non-stub row for the chunker; only no-change batches
  skip that. The chunker is not incremental.
- Crop upload keeps its `409` on a moved scene (the head moves only when ink moved).
