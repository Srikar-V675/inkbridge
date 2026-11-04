# 0038: chunk scale cap, local scale, id churn and anchor successors (INK-081)

Status: accepted. Real-canvas acceptance (hand-boxed groups, tablet overlay check) is open until INK-095 merges.

## Premise correction
The threshold was never a fixed 20 px: `_proximity` already uses `k * median(max(w, h))` over every clustering element. The failure is a canvas that mixes zoom levels, where one page-wide median fits neither: with 1x and 10x handwriting half and half the median is 200, the threshold 300, and 1x paragraphs 170 apart glue together.

## Measurement (`scripts/chunk_scale_eval.py`, synthetic mixed-zoom fixture `server/tests/chunk_scale_fixture.py`)
323 elements: 2 paragraphs of 1x writing, 2 of 10x writing 6000 px right, 3 tall rectangles. Global median 200. Nearest-neighbour gaps: 0-1: 32, 1-5: 160, 5-20: 32, 20-100: 96, 100-500: 3.

| config | before: chunks / spanning | after: chunks / spanning |
|---|---|---|
| k=1.5 (default) | 4 / 1 | 5 / 0 |
| k=1.0 | 6 / 1 | 7 / 0 |

"Spanning" = chunks holding two paragraphs or both zoom areas. Lowering k alone does not help (still 1).

## Candidates
- (A) cap only: not enough. The glued 1x group is 150 x 640 px with own median 20, far under 80 x 20 = 1600.
- (B) lower k: not enough, see above, and it moves every content_hash boundary.
- (C) local scale: shipped, with the cap. A group whose own median is under half the page median is re-clustered with its own median (recursively); k is unchanged.
- Cap shipped too (`ChunkerConfig.max_extent = 80`): a chunk is at most 80 x its own median wide or tall; an oversize group is cut at its largest gap (sweep over the longer axis), recursively; bound text goes back to its container; pinned chunks are never capped. 80 is a guess; tune on the real canvas after INK-095.

## Id churn (`scripts/chunk_churn_replay.py`, one scene save per stroke)
New ids per 20 appended strokes, containment off / 0.6: one growing line 2,0 / 1,0; 1x page only max 2 / 1; 10x page only max 2 / 1 (the first count is the chunk's creation). Gate (at most 2 per 20, 0 while appending to one chunk) is met with containment OFF, except the 1 -> 2 stroke step (J = 0.5 is not above 0.5) which leaves one orphan per new chunk; containment 0.6 removes those orphans.
Decision: containment stays off by default (0029 asked for real-page validation, and only synthetic data exists). Hysteresis is not needed. `test_appending_strokes_keeps_chunk_id` guards the append case from 3 strokes.
Not solved: a mixed replay (10x strokes arriving while 1x ink still sets the page median) churns 12-20 ids per 20 strokes, because the global median decides the threshold until the new ink outweighs it. Raising the threshold locally for large strokes is a follow-up if the real canvas shows it.

## Anchors
`write_text` / `draw_diagram` with an anchor that a re-chunk orphaned now place next to its live successor (`successor_of`, cycle-guarded). The op payload reports `anchor_resolved`. An orphan with no successor keeps its own last box. MCP signatures unchanged.

## Consequences
Cap and local scale move chunk boundaries on mixed-zoom canvases, so ids may change on the first save after deploy. Notes exported before this fix need a re-export (check_sync reports `replaced`, decision 0020); run the INK-055 export demo only after. Open until INK-095: hand-box comparison on the real `default` canvas, tablet check that Show chunks boxes match visible groups.
