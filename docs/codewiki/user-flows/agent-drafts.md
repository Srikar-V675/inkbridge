# Agent writes text or a diagram as drafts

**Story:** as a note-taker, I want Claude to add text or a diagram next to my ink without ever touching my strokes, and to decide what stays.

1. Claude calls `write_text` (optionally with a chunk `anchor`), `draw_diagram` (Mermaid flowchart), or `create_canvas` first for a blank canvas.
2. The MCP server POSTs `/documents/{id}/ops`. The API validates (no existing element ids, flowchart only, anchor not orphaned) and stores it `pending`.
3. `ws.py` pushes `op.pending`; on reconnect the server replays pending and delivered ops.
4. The browser (`sync/opsSocket.ts`, `drafts/drawOp.ts`, `drafts/draftStore.ts`) draws the op from its own draft store as dashed elements tagged `customData {author:"agent", draft:true, op_id}`, measures them and replies `op.measured`; the server searches candidate spots near the anchor (`agent/placement.py`, decision 0094) and pushes `op.placed`, and the client moves the draft there. Mermaid is converted in the browser; a parse error comes back as `op.failed`.
5. `draw_diagram` polls until the ack (default 20 s). With no browser it marks the op `expired` and returns an error naming the canvas URL.
6. Drafts live in the `agent_ops` row, not in the scene: they are kept out of saves, the device journal and the live delta, and are never chunked, read or exported until accepted (decisions 0086, 0090).
7. Each draft has Accept / Reject pills on it (`drafts/DraftPills.tsx`, decision 0115); the draft tray and bar (`drafts/DraftBar.tsx`) hold Accept all / Reject all, and a tether line points at the anchor. A toast offers Undo.
   - Accept: `POST /ops/{id}/accept`, one server transaction that writes the elements into `scene_elements` and publishes `scene.delta`. Idempotent.
   - Reject: `POST /ops/{id}/reject`. `POST /ops/{id}/unaccept` reverses an accept.
   - Accepted agent ink becomes its own chunk with an `agent` reading and is never sent to a reader (decision 0044).

```text
draft (placed) --Accept--> POST accept --> elements in scene_elements --> ordinary content
draft (placed) --Reject--> POST reject --> draft dropped
```

Text is sized from the handwriting and wrapped at a server-set `wrap_chars`; `write_text` takes `size` small/normal/large (decisions 0045, 0094). For an Ask answer the draft is placed right under its anchor with a flow arrow and an "Answer:" lead (decisions 0115, 0116, `agent/flow.py`). `edit_diagram` makes a revision of a diagram object whose Accept replaces only untouched shapes (decision 0100).

Invariant: measured and accepted elements must carry the op's `id_prefix`; agent ops can only add elements (`tests/test_ops_api.py`). Decisions 0009, 0012, 0019, 0023, 0026, 0032, 0086, 0090, 0094.
