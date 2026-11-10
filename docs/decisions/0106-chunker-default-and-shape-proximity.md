# 0106: Chunker default stays v1; v2 shapes join by arrow or overlap

INK-186. Status: accepted.

## Context

Arrows and shapes landed in one big chunk. v2 (decision 0081) is built and switchable per canvas, so "turn it on" was a default question plus any v2 defect. Measured on synthetic data:

- A flowchart of four 160x70 boxes joined by bound arrows: v1 gives 1 chunk at every gap. v2 gave 1 chunk at gaps 80 to 200 because `cluster_lines` joined boxes that were within 1.5 x the median size, before any arrow was considered.
- Real-scale synthetic handwriting (`t10`, 528 strokes): v1 gives 4 paragraph chunks, v2 gives 329. These fixtures use placeholder stroke height and pitch (decision 0053) and v2 thresholds await E5 (decision 0078), so this is not proof either way.
- Fixture diagrams: arrows (200) are shorter than the boxes (700), so by the tick rule (techref 5.x, `arrow_merge`) they merge their boxes in both versions: 1 chunk each. Not changed.

## Decision

- The default stays `v1` (`INKBRIDGE_CHUNKER` unset). A deliberate decision, pinned by a test.
- v2 fix: two drawn shapes (rectangle, diamond, ellipse) that do not overlap never join by proximity; arrows (or overlap or nesting) decide. Text near a shape still joins. v1 is untouched (golden file stays green).
- `/health` reports `chunker`, the default for canvases with no setting of their own; a canvas's own value is in `GET /documents`.

## Consequences

- Flowchart gap 200 and more: 4 chunks and 3 links in v2 (was 1 chunk). Gaps at or under the median element still merge (tick rule).
- Switch a canvas with `PATCH /documents/{id}` `{"chunker": "v2"}` or set `INKBRIDGE_CHUNKER=v2`.
- Flip the default only when the owner confirms on real pages that handwriting is not shattered into word-sized chunks, or E5 recalibrates the v2 thresholds.

Superseded in part by 0110 (default is now v2).
