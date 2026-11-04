# Deep Dive: web ops socket and drafts (`opsSocket.ts`, `drafts.ts`, `drawOp.ts`)

Browser side of the agent write-back loop (INK-042, decisions 0009, 0012). Server side: [ops-queue-and-websocket.md](ops-queue-and-websocket.md).

## `OpsSocket` (`opsSocket.ts`)

Client for `WS /ws?document=<id>`.
- **Reconnect**: on close, wait `BACKOFF_MS = [500, 1000, 2000, 5000, 10000]` (indexed by consecutive failures, reset on open) and start again. A stale close event from a replaced socket is ignored (`this.ws !== ws`).
- **Messages in**: `op.pending` -> `enqueue`; `chunks.updated` -> `onChunksUpdated` (crop sync hooks in here); `op.updated`; `op.error`. Unparseable frames are ignored.
- **One op at a time**: `enqueue` chains onto a promise queue and keeps a `busy` set, so a replay of an op still being drawn is skipped. On success it sends `op.applied {op_id, element_ids}`; on any throw `op.failed {op_id, error}`.
- **Safe send**: a socket that is closed or still connecting throws on `send`; the message is dropped instead. The server replays an unacked op on the next connect and the drawn drafts are found and acked then. Throwing would report a drawn op as failed and a rejected queue would never run another op.
- Injectable `createSocket` and `setTimer` for tests (`idle()` resolves when the queue is empty).

## Pure draft helpers (`drafts.ts`)

No Excalidraw import, so they run under Node's test runner. Rules: drafts only ever **add** elements; every element an op creates gets an id starting with the op's server-issued `id_prefix`; each is tagged `customData {author:"agent", draft:true, op_id}` and drawn dashed.

| Function | Behaviour |
|---|---|
| `opElements(elements, prefix)` | Elements already drawn for this op (a replay must not draw twice) |
| `prefixIds(elements, prefix)` | New ids `<prefix><n>`; rewrites `containerId`, `frameId`, `boundElements`, `startBinding`/`endBinding`; references to ids outside the set become `null`/dropped so a draft never points at user ink; `groupIds` are re-keyed to `<prefix>g<n>` so a draft can never join a user's group |
| `placeAt(elements, at)` | Translates so the top-left (point extents for strokes) lands at the server's placement |
| `markDraft(elements, opId)` | `strokeStyle: "dashed"`, text opacity 70, adds the `customData` tag |
| `toDrafts(converted, op)` | The pipeline after conversion: prefix, place, mark |
| `rejectOp(elements, prefix)` | Soft-deletes (`isDeleted: true`, `version + 1`) every element whose id starts with the prefix, a sweep that also catches elements the ack did not list, and nothing else; the version bump keeps the delete through autosave and conflict merge |

## `drawOp` (`drawOp.ts`, browser only)

`drawOp(api, op, persist)`:
1. If elements with the op's prefix already exist (replay after a reload or reconnect), `await persist(scene)` again and return their ids: the first ack may have been lost before the drafts were saved.
2. `skeletonFor(op)`: for `write_text` a text skeleton; for `draw_diagram` dynamic-import `@excalidraw/mermaid-to-excalidraw` and `parseMermaidToExcalidraw`. A parse error throws "Mermaid could not be parsed: ...". If any parsed element is an `image` (a non-flowchart diagram) it throws "Only Mermaid flowcharts are supported".
3. Wait for `document.fonts.load("20px Excalifont")`; the text size drawn is the op's server-computed `font_size` (20 for ops stored before INK-066); measuring text before the hand-drawn font loads makes boxes too narrow and clips text.
4. `convertToExcalidrawElements(skeleton, {regenerateIds: true})`, then `toDrafts`; no elements throws "the op produced no elements".
5. `api.updateScene` appends the drafts, then `await persist(...)` (the caller acks only after the scene containing the drafts is saved, because an applied op is never replayed, so an unsaved draft lost to a reload would never come back). Returns the draft ids.

## Accept / Reject (`resolve.ts`, `DraftBar.tsx`, decision 0026)

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
