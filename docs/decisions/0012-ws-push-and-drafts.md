# 0012: WebSocket push and draft rendering

Status: accepted (INK-042)

Code: `server/src/inkbridge/api/ws.py`, `web/src/opsSocket.ts`, `web/src/drafts.ts`,
`web/src/drawOp.ts`.

- **Message shape.** Every message has a `type`. The op's own kind therefore travels as `op_type`:
  `op.pending {op_id, op_type, payload}`; `payload` carries `placement` and `id_prefix`. Beyond the
  tech-ref table the server also sends `op.updated {op_id, status, error}` on every status change
  (WS ack or `PATCH`), so other tabs and the later Accept/Reject UI stay in step, and
  `op.error {op_id, code, detail}` when it refuses an ack (`existing_element_id`,
  `invalid_transition`, `not_found`, `bad_ack`). Malformed messages get `{type: "error"}` and the
  socket stays open. An unknown document closes the socket with code 4404.
- **Delivery and replay.** On connect the server replays every `pending` and `delivered` op of the
  document, after registering the socket, so an op created during the replay is still pushed at
  least once. An op becomes `delivered` once one browser got it (`mark_delivered`, which now runs
  under `BEGIN IMMEDIATE` and reports whether it moved the op). HTTP routes run in the
  threadpool, so they hand sends to the socket's event loop (`hub.publish`, fire and forget).
- **Idempotence by op_id.** The browser draws an op only if no element carries the op's
  `id_prefix`; a replayed op that is already on the canvas is acked again with the ids it finds
  (the server treats a same-set re-ack as a no-op). The client handles ops one at a time and
  ignores a second copy of an op it is still drawing.
- **Ids.** Converted elements get ids `<id_prefix><n>`; every reference between them (bound text
  `containerId`, a container's `boundElements`, arrow `startBinding`/`endBinding`, `frameId`) is
  rewritten, and references to anything outside the op are dropped, so a draft never points at
  user ink. Reject (UI in INK-045) is `rejectOp`: a sweep that soft-deletes every element with the
  op's prefix, not only the acked ids, and touches nothing else.
- **Drafts.** Tagged `customData {author: "agent", draft: true, op_id}`, `strokeStyle: "dashed"`,
  text at 70 % opacity. They are ordinary scene elements, so autosave persists them and a reload
  keeps them. The ack is sent right after `updateScene`, before the autosave.
- **Flush on arrival.** When an op arrives the client starts saving its pending changes, so the
  server's placement of the next op sees the newest ink. The current op was already placed when
  it was queued.
- **Mermaid** is converted in the browser (`parseMermaidToExcalidraw`, loaded on first use, then
  `convertToExcalidrawElements` with fresh ids). A parse error, or a diagram that comes back as an
  image (not a flowchart), is reported as `op.failed` with the message.
- **Fonts.** Text is measured when it is converted; the client waits for Excalifont to load
  first, otherwise the box is too narrow and clips the text.
- **chunks.updated** is sent after every scene save with the new version and the ids of active
  regions whose crop is stale. Crop sync (INK-057) hooks into `OpsSocket.onChunksUpdated`.
