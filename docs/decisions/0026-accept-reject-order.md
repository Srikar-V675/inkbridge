# 0026: Accept, Reject and Accept all ordering

Status: accepted (INK-045)

Code: `web/src/resolve.ts`, `web/src/DraftBar.tsx`, `server/src/inkbridge/api/ops.py`
(`PATCH /ops/{id}`, unchanged).

- **No server change.** `PATCH /ops/{id}` already moves `applied -> accepted|rejected` (409 otherwise)
  and broadcasts `op.updated`. The server never edits the scene; the browser owns it. So resolving a
  draft adds no endpoint and no change to `docs/mcp-tools.md`.
- **Accept saves before it PATCHes.** The client first rewrites the op's elements locally (drop
  `customData.draft`, keep `author` and `op_id`, solid stroke), then saves the scene and confirms it
  settled, and only then sends `PATCH accepted`. The reverse order would leave a failed save with the
  stored elements still `draft: true` while the op is `accepted`, and the chunker, recognizer and export
  would exclude those elements forever. If the save does not settle, nothing is patched and the user
  can retry.
- **Reject PATCHes before it sweeps.** The client sends `PATCH rejected` first and removes the drafts
  locally only for ops the server accepted. If the PATCH fails, the drafts stay and the user can retry.
  The existing `op.updated` sweep (dead ops) makes other tabs follow.
- **Remove by id prefix, never by tag.** Reject removes elements whose id starts with `<op_id>:`
  (`rejectOp`). `customData` is written by the client, so a user element carrying a forged
  `draft`/`op_id` must never be matched. `draftOpId` holds that check once; `draftOps` and the selection lookup both use it.
- **Accept restores text opacity to 100.** Drafts draw text at 70 % opacity and the original opacity is
  not stored, so accept sets text back to 100 (the converted default). A Mermaid label that came with a
  different opacity changes on accept. Accepted that trade-off rather than storing a second value.
- **"All" means the drafts in the scene.** Accept all and Reject all act on the op ids found on the
  canvas (elements with `customData.draft` and an `op_id`), resolved with their PATCHes sent in parallel (results keep op order). Accept all
  makes one scene update and one save for the whole batch. A 409 (`invalid_transition`, for example
  an op still being drawn or already resolved) is reported for that op and does not stop the batch.
- **Accept checks op status first.** Before rewriting anything, the client asks
  `GET /documents/{id}/ops?status=applied` and accepts only draft ops in that set. Others (still
  `delivered`, already resolved elsewhere, expired) are skipped and reported as "N not ready"; the
  scene is left alone for them. If the check itself fails, nothing is accepted ("could not check op
  status"). Reject does not check; the PATCH's 409 is enough because nothing is rewritten first.
- **Retry after a failed PATCH.** Accept saves the scene before it PATCHes, so a failed PATCH leaves the
  op `applied` with no draft elements and nothing on the canvas to click. DraftBar keeps those op ids
  and shows "Retry accept (N)", which re-sends `PATCH accepted` only (no scene rewrite, no save) and
  clears the ids that succeed. The list lives in component state, so a reload loses it; the op then
  stays `applied`, which is harmless (the elements are already ordinary content).
- **Verdict updates skip undo history (`captureUpdate: NEVER`).** The scene update that applies Accept or
  Reject is not recorded, so undo cannot step back over it and bring `draft: true` (or a rejected draft)
  back under an op the server already resolved. Checked in headless Chromium: draw a stroke, receive a
  draft, Accept all, Ctrl+Z; the stroke is undone (`isDeleted`), the accepted text stays and carries no
  draft tag. This replaces an earlier `api.history.clear()`, which also cost the user undo for strokes
  made before the verdict.
- **Stroke style is forced solid on accept.** Drafts are drawn dashed and the original style is not
  stored, so every accepted element becomes solid, even a Mermaid shape that came dashed.
- **Second tab lags.** Another tab on the same canvas only learns of a verdict through `op.updated`
  and the next scene sync, so for a moment it still shows the drafts and its buttons would 409 (shown as
  "not ready"). It converges on the next sync; no cross-tab locking.

