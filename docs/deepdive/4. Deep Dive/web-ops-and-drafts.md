# Deep Dive: web ops socket and drafts (`sync/opsSocket.ts`, `drafts/drafts.ts`, `drafts/drawOp.ts`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

Browser side of the agent write-back loop (INK-042, decisions 0009, 0012). Server side: [ops-queue-and-websocket.md](ops-queue-and-websocket.md).

## How drafts work now (Updated 13 Nov 2026)

Everything below this section is the 26 Oct design, where drafts were scene elements saved with the scene, acked as `op.applied` and resolved by `PATCH`. Since INK-114 and INK-115 (decisions 0086, 0090) the draft is the `agent_ops` row and the client only draws and measures it. Invariants kept: agent ops only add elements; every element carries the op's `id_prefix`.

**Flow.**
1. `op.pending` arrives on the socket (`sync/opsSocket.ts`); `drafts/drawOp.ts` `measureOp` converts the op (text skeleton, Mermaid via `mermaid-to-excalidraw`, or the graph IR through `drafts/graphLayout.ts` `layoutGraph` for diagram objects; `wrapText` uses the server's `wrap_chars`; font size is the op's `font_size`) and the socket sends `op.measured {op_id, elements, width, height}`. The browser no longer places anything and no longer acks `op.applied`; failures still send `op.failed`.
2. The server places the draft (`agent/placement.py`) and pushes `op.placed {op_id, elements, placement, anchor}`. Placed ops are replayed on every connect, and `fetchDrafts` (`GET /documents/{id}/drafts`) loads the open ones.
3. `drafts/draftStore.ts` (`createDraftStore`) holds the `PlacedOp` list (`id`, `payload.id_prefix`, `anchor_resolved`, `question_id`, `elements`, `box`). `reconcile(scene, ops)` is the pure function from the placed ops to the draft elements shown in the scene; `offsetOf` and `reloadWithDrafts` keep drafts on screen across scene reloads. Draft elements are tagged `customData {author:"agent", draft:true, op_id}` and dashed (`drafts/drafts.ts`, `markDraft`), but they never enter scene saves, the device journal or the live delta (`isDraftTagged`).
4. **Resolving** (`drafts/resolve.ts`): `accept(opId, dx, dy)` -> `POST /ops/{id}/accept` (the offset says where the user dragged the draft), `reject(opId)` -> `POST /ops/{id}/reject`, `unaccept(opId)` -> `POST /ops/{id}/unaccept`. All use an 8 s timeout and never throw; they return `{ok}` or a message. Accept is one server transaction that writes the elements into the scene and publishes `scene.delta`. The server has no un-reject, so `DraftBar` holds a Reject until its Undo toast expires.
5. **UI.** `drafts/DraftPills.tsx` puts an Accept/Reject pill at each in-view draft's top-right corner (`draftPills.ts` `pillPosition`: above the corner, flipped below if there is no room, clamped inside the free area; decision 0115). `drafts/DraftBar.tsx` is the tray and card ("N drafts on this canvas", `draftUi.ts` `trayLabel`), shows Accept all / Reject all when two or more are open (`showBulk`), and posts Undo toasts (`verdictToast`). `drafts/Tether.tsx` draws a dashed line from a draft to the chunk it answers. `drafts/draftView.ts` pans a new draft into view, or offers a "New draft" chip and Jump (`planReveal`, `createUnseen`, decision 0054); it also names the flow arrow (`FLOW_ARROW`) an answer draft carries from its anchor (decision 0116).

**Tests.** `draftStore.test.ts`, `draftPills.test.ts`, `draftUi.test.ts`, `draftView.test.ts`, `graphLayout.test.ts`, `resolve.test.ts`, `drafts.test.ts`, `opsSocket.test.ts`.

## `OpsSocket` (`sync/opsSocket.ts`, 26 Oct snapshot; messages in now also include `op.placed`, `scene.delta`, `question.update`, `question.delta`, `offer.*` and `agent.activity`)

Client for `WS /ws?document=<id>`.
- **Reconnect**: on close, wait `BACKOFF_MS = [500, 1000, 2000, 5000, 10000]` (indexed by consecutive failures, reset on open) and start again. A stale close event from a replaced socket is ignored (`this.ws !== ws`).
- **Messages in**: `op.pending` -> `enqueue`; `chunks.updated` -> `onChunksUpdated` (crop sync hooks in here); `op.updated`; `op.error`. Unparseable frames are ignored.
- **One op at a time**: `enqueue` chains onto a promise queue and keeps a `busy` set, so a replay of an op still being drawn is skipped. On success it sends `op.applied {op_id, element_ids}`; on any throw `op.failed {op_id, error}`.
- **Safe send**: a socket that is closed or still connecting throws on `send`; the message is dropped instead. The server replays an unacked op on the next connect and the drawn drafts are found and acked then. Throwing would report a drawn op as failed and a rejected queue would never run another op.
- Injectable `createSocket` and `setTimer` for tests (`idle()` resolves when the queue is empty).

## Pure draft helpers (`drafts/drafts.ts`)

No Excalidraw import, so they run under Node's test runner. Rules: drafts only ever **add** elements; every element an op creates gets an id starting with the op's server-issued `id_prefix`; each is tagged `customData {author:"agent", draft:true, op_id}` and drawn dashed.

| Function | Behaviour |
|---|---|
| `opElements(elements, prefix)` | Elements already drawn for this op (a replay must not draw twice) |
| `prefixIds(elements, prefix)` | New ids `<prefix><n>`; rewrites `containerId`, `frameId`, `boundElements`, `startBinding`/`endBinding`; references to ids outside the set become `null`/dropped so a draft never points at user ink; `groupIds` are re-keyed to `<prefix>g<n>` so a draft can never join a user's group |
| `placeAt(elements, at)` | Translates so the top-left (point extents for strokes) lands at the server's placement |
| `markDraft(elements, opId)` | `strokeStyle: "dashed"`, text opacity 70, adds the `customData` tag |
| `toDrafts(converted, op)` | The pipeline after conversion: prefix, place, mark |
| `rejectOp(elements, prefix)` | Soft-deletes (`isDeleted: true`, `version + 1`) every element whose id starts with the prefix, a sweep that also catches elements the ack did not list, and nothing else; the version bump keeps the delete through autosave and conflict merge |

## `drawOp`, 26 Oct design (`drafts/drawOp.ts` now exports `measureOp` instead)

`drawOp(api, op, persist)`:
1. If elements with the op's prefix already exist (replay after a reload or reconnect), `await persist(scene)` again and return their ids: the first ack may have been lost before the drafts were saved.
2. `skeletonFor(op)`: for `write_text` a text skeleton; for `draw_diagram` dynamic-import `@excalidraw/mermaid-to-excalidraw` and `parseMermaidToExcalidraw`. A parse error throws "Mermaid could not be parsed: ...". If any parsed element is an `image` (a non-flowchart diagram) it throws "Only Mermaid flowcharts are supported".
3. Wait for `document.fonts.load("20px Excalifont")`; the text size drawn is the op's server-computed `font_size` (20 for ops stored before INK-066); measuring text before the hand-drawn font loads makes boxes too narrow and clips text.
4. `convertToExcalidrawElements(skeleton, {regenerateIds: true})`, then `toDrafts`; no elements throws "the op produced no elements".
5. `api.updateScene` appends the drafts, then `await persist(...)` (the caller acks only after the scene containing the drafts is saved, because an applied op is never replayed, so an unsaved draft lost to a reload would never come back). Returns the draft ids.

## Accept / Reject, 26 Oct design (superseded by the section above; decision 0026)

| Piece | Behaviour |
|---|---|
| `draftOpId(e)` | The op id of a live draft, or null. Requires `customData.draft`, a string `op_id`, and an element id starting `<op_id>:` (customData is client-writable) |
| `draftOps(els)` | Ops with live drafts and their element counts |
| `acceptOp(els, prefix)` | Drops the `draft` flag (keeps `author`, `op_id`), solid stroke, text opacity 100, `version + 1` |
| `applyVerdict(ids, verdict, ports)` | Accept: check the server holds the ops as `applied` (`GET /documents/{id}/ops?status=applied`), rewrite locally, save and confirm settled, then `PATCH accepted`. Reject: `PATCH rejected` first, then `rejectOp` for the ops the server accepted |
| `retryAccept(ids)` | Re-sends `PATCH accepted` when the scene was saved but the PATCH failed (INK-091 notes a stuck case when the save itself fails) |

`DraftBar` is plain DOM at the bottom right: "N drafts (M elements)", Accept / Reject for the selected draft(s), Accept all / Reject all, a status line (for example "2 not ready"), and "Retry accept (n)". Each PATCH has an 8 s timeout. Ports are injected so the order is unit-tested without Excalidraw.

## Testing

`web/tests/opsSocket.test.ts`, `web/tests/drafts.test.ts`, `web/tests/resolve.test.ts`; server `tests/test_ws.py`.
