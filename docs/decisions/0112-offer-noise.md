# 0112: Offer noise (INK-197)

Status: accepted. Follows 0089, 0091, 0105, 0107.

## Why

The owner test on 10 Nov logged 8 candidates on one canvas (`question` 2, `dangling_arrow` 4, `to_note` 1, `related` 1). Offers kept appearing on old ink, on a flowchart, and for relations nobody asked for. The page felt messed with.

## The four rules (`agent/detectors.py`)

1. **Just-written ink only.** `scan` keeps the chunks whose `updated_at` is within `RECENT_S` (120 s) of now and feeds only those to `question`, `open_equation`, the dangling arrow, and `sketch`. `updated_at` on a chunk moves when its `stroke_hash` changes (`db/chunks.py` `_sync_chunks`), not when a reading arrives, so it is the "just written" signal. `stale_note`, `stale_diagram` and `markup` keep their own change keys and are not filtered.
2. **One open offer at a time.** `run` returns early while any offer for the canvas is `open` (logged as `held=open_offer`). After a create it stops, so the best candidate wins and the rest are dropped. Dropped candidates are not queued: a later scan finds them again if the ink is still fresh. Per-kind dedupe through `seen` is unchanged.
3. **`related` and `to_note` are never proactive.** `scan(conn, doc, slow=False)` calls them only when `slow=True`. `run` takes the same flag. Nothing in the API passes it, so the on-request path is unused for now. The "after long inactivity on a canvas with real text" path is deferred: scans only run on save, so there is no idle trigger yet.
4. **Dangling arrow is a long, straight, headed native arrow.** `DANGLE_TOL` 80 (was 40), `DANGLE_MIN_LEN` 150 scene units, `DANGLE_STRAIGHT` 0.9 (chord over path length), and an `endArrowhead` is required. Only `type == "arrow"` was ever considered, so a freedraw handwriting stroke never qualifies. The v2 connector chunk path (`_dangling`) is unchanged.

Start values are hypotheses to tune on real pages: `RECENT_S` 120, `DANGLE_TOL` 80, `DANGLE_MIN_LEN` 150, `DANGLE_STRAIGHT` 0.9.

## Consequences

- A reading that arrives more than 2 minutes after its ink is missed: the chunk is no longer fresh, so no offer is made. This is a shortcut, since a slow or rate-limited read can miss the window.
- Moving or resizing old ink changes its `stroke_hash`, so it counts as just written for 2 minutes and can give an offer. Accepted for now.
- Muting (0089) and budget (3) still apply. The budget is now rarely the limit, since only one offer is open at a time.
- Tests: `tests/test_detectors.py` pins each rule with fixtures (old ink, related and to_note off the slow path, one-at-a-time, the dangling arrow negatives and tolerance, a freedraw stroke, a flowchart with a free arrow giving at most one).

## Shortcuts

- Rotation is still ignored in the tip-to-box distance (see 0107).
