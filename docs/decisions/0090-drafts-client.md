# 0090: Drafts client (INK-115)

Status: accepted. Builds on the server side in INK-114 (placed ops, `/drafts`, accept/reject/unaccept).

- **The scene is a function of the placed-op list.** `draftStore.reconcile(scene, placedOps)` adds the draft elements of every placed op (once; a replayed `op.placed` or a refetch adds nothing) and removes live draft elements whose op is no longer placed. Drafts are still Excalidraw elements (dashed, `customData.draft`), inserted with `captureUpdate: NEVER`. The store is filled from `GET /documents/{id}/drafts` on connect, on `op.placed` (a refetch, since the message has no box) and on `op.updated` back to `placed` (unaccept); any other status removes the op.
- **The id-prefix rule decides what is a draft.** Matching goes through `draftOpId` (the id must start with `<op_id>:`), never the tag alone, so a user element with a copied tag survives. Tests fail if the check is removed.
- **The sender never sees drafts.** `SceneSync.notify` filters draft-tagged elements (live or erased) before journal, delta and snapshot, so drafts are not saved by the browser at all. The old save-then-ack loop (`persist`, `SAVE_ATTEMPTS`) is deleted; the browser only measures (`op.measured {elements, width, height}`) and the server places.
- **Accept carries the drag offset.** `offsetOf` is the draft's bbox origin minus the placed box origin; `POST /ops/{id}/accept {dx, dy}`. The dashed elements leave the scene at once; the server's `scene.delta` brings the solid ones. After an unaccept the server deletes the solid elements; `reconcile` replaces such a deleted, untagged element under a placed prefix with the draft again.
- **Reject is deferred for the toast's 6 s** because the server has no unreject: the card is hidden, `Draft removed.` has Undo, and `POST /reject` is sent when the toast expires, is replaced or the bar unmounts. A tab closed inside the window leaves the draft placed (recoverable). Undo after Accept calls `unaccept` (server window 60 s; 409 shows "Too late to undo").
- **A draft erased by the user is ignored**: soft-deleted draft elements count as present, so they are not re-added. The card stays and Reject cleans up.
- **Open thread opens the Ask panel.** There is no per-op thread on the server yet; the link is the v1 behaviour.
- **Tether**: chunk bounds for `payload.anchor_resolved` come from `listChunks` per op and are drawn as a dashed path to the draft; nothing is drawn if the chunk is missing.
- The pan-to-draft `reveal` fires the first time an op id appears in the store, so a reload or reconnect replay does not pan.
