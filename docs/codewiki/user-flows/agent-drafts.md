# Agent writes text or a diagram as drafts

**Story:** as a note-taker, I want Claude to add text or a diagram next to my ink without ever touching my strokes, and to decide what stays.

1. Claude calls `write_text` (optionally with a chunk `anchor`), `draw_diagram` (Mermaid flowchart), or `create_canvas` first for a blank canvas.
2. The MCP server POSTs `/documents/{id}/ops`. The API validates (no existing element ids, flowchart only), places the op beside the anchor (`agent/placement.py`), and stores it `pending`.
3. `ws.py` pushes `op.pending`; on reconnect the server replays pending and delivered ops.
4. The browser (`sync/opsSocket.ts`, `drafts/drawOp.ts`, `drafts/drafts.ts`) draws dashed elements tagged `customData {author:"agent", draft:true, op_id}` and replies `op.applied {op_id, element_ids}`. Mermaid is converted in the browser; a parse error comes back as `op.failed`.
5. `draw_diagram` polls until the ack (default 20 s). With no browser it marks the op `expired` and returns an error naming the canvas URL.
6. Drafts are saved with the scene but ignored by chunking, recognition and export.
7. The draft bar (`drafts/DraftBar.tsx`) shows the draft count with Accept / Reject for the selected draft and Accept all / Reject all.
   - Accept: rewrite the elements locally (solid, no draft flag), save the scene, then `PATCH accepted`. If the save fails nothing is patched.
   - Reject: `PATCH rejected` first, then remove elements whose id starts with `<op_id>:`.
   - If the PATCH fails after a successful accept save, a "Retry accept" button re-sends it.

```text
draft (applied) --Accept--> save scene --> PATCH accepted --> ordinary content
draft (applied) --Reject--> PATCH rejected --> sweep <op_id>: elements
```

Text is sized from the handwriting (median stroke height x 1.5, clamped 18..64, default 28); `write_text` takes `size` small/normal/large.

Invariant: acks must carry the op's `id_prefix`; agent ops can only add elements (`tests/test_ops_api.py`). Decisions 0009, 0012, 0019, 0023, 0026, 0032. Known issues: drafts can land far apart and agent text can still be small (see roadmap).
