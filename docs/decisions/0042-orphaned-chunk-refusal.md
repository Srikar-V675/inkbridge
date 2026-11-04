# 0042 Orphaned chunks are followed or refused, never read as current (INK-084)

**Problem.** On 4 Nov a `draw_diagram` anchored to a chunk whose ink had been deleted still drew beside it: an orphan with no successor returned its own last bbox. `get_region` of such a chunk also served its old crop and reading as if current.

**Decision.**
- `_resolve_anchor` follows `successor_of` to an active chunk (INK-081). A dead end (orphan with no successor) or a cycle raises `AnchorGone`, a subclass of `AnchorNotFound`, and the API answers 422 `anchor_gone` with a message naming `read_canvas`. No op row is inserted. `AnchorNotFound` stays for ids that were never on the canvas.
- Resolution happens once, at creation. Placement is then fixed, because the draft is visible and the user can reject it; nothing re-resolves at apply time. `payload.anchor_resolved` records the chunk actually used, and the MCP replies return it as `anchor_used` with a `note` when it differs from the requested anchor. Replaying the same `op_id` returns the stored op without re-validating.
- `GET /regions/{id}` adds `live_successor` for non-active chunks (via `db.sync._live_successor`, null on a dead end). `/image`, `/ink`, `/sketch` and `/sketch.png` of an orphan return 410 naming the successor or `read_canvas`; `?history=true` returns the old data. Nothing in the web app reads orphan crops (crop sync only PUTs for active `png_stale` chunks).
- MCP `get_region` of a non-active chunk returns only `{id, status, live_successor, note}` before any ink, sketch or image request. MCP has no `history` flag.

**Unchanged.** `check_sync` keeps following successors (decision 0020). `read_canvas` lists active chunks only. `answer_question` sources and the Ask focus only format-check chunk ids (0035); reading them goes through the guarded `get_region`.

**No depth bound** beyond cycle detection: `successor_of` holds a single id (decision 0011), so a chain has no ties, and the `seen` set ends cycles.

**Known gap.** A draft queued beside a chunk that dies later stays where it was placed.
