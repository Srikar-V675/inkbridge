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
  `draft`/`op_id` must never be matched. `draftOps` applies the same prefix check when counting drafts.
- **Accept restores text opacity to 100.** Drafts draw text at 70 % opacity and the original opacity is
  not stored, so accept sets text back to 100 (the converted default). A Mermaid label that came with a
  different opacity changes on accept. Accepted that trade-off rather than storing a second value.
- **"All" means the drafts in the scene.** Accept all and Reject all act on the op ids found on the
  canvas (elements with `customData.draft` and an `op_id`), resolved one PATCH at a time. Accept all
  makes one scene update and one save for the whole batch. A 409 (`invalid_transition`, for example
  an op still being drawn or already resolved) is reported for that op and does not stop the batch.
