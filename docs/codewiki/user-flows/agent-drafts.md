# Agent writes text or a diagram as drafts

**Story:** as a note-taker, I want Claude to add text or a diagram next to my ink without ever touching my strokes, and to decide what stays.

1. Claude calls `write_text` (optionally with a chunk `anchor`), `draw_diagram` (Mermaid flowchart), or `create_canvas` first for a blank canvas.
2. The MCP server POSTs `/documents/{id}/ops`. The API validates (no existing element ids, flowchart only), places the op beside the anchor (`placement.py`), and stores it `pending`.
3. `ws.py` pushes `op.pending`; on reconnect the server replays pending and delivered ops.
4. The browser (`opsSocket.ts`, `drawOp.ts`, `drafts.ts`) draws dashed elements tagged `customData {author:"agent", draft:true, op_id}` and replies `op.applied {op_id, element_ids}`. Mermaid is converted in the browser; a parse error comes back as `op.failed`.
5. `draw_diagram` polls until the ack (default 20 s). With no browser it marks the op `expired` and returns an error naming the canvas URL.
6. Drafts are saved with the scene but ignored by chunking, recognition and export.
7. Accept / Reject / Accept all: **planned (INK-045)**. `PATCH /ops/{id}` already accepts `accepted`/`rejected`.

Invariant: acks must carry the op's `id_prefix`; agent ops can only add elements (`tests/test_ops_api.py`). Decisions 0009, 0012, 0019, 0023.
