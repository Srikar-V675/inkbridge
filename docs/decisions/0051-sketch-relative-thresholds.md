# 0051: sketch thresholds are relative to the ink

INK-085. Pass 1 of the sketch reading used an absolute 20 px minimum for a freehand loop. On a zoomed-out handwriting page every `o` and `a` passed it, and hundreds of strokes came back as nodes or unattached.

Decision:
- A loop is a node only if its diagonal is at least 5% of the diagonal of all live elements (`MIN_NODE_FRACTION`).
- With at least 8 freedraw strokes and a median stroke diagonal below that 5% line (a handwriting page), the loop must also be at least 2x the median diagonal (`LETTER_FACTOR`). The median test is skipped when the median stroke is itself big (a chart of boxes), otherwise it would raise the bar above the nodes, and below 8 strokes so a lone box still reads.
- A small absolute floor of 12 px (`MIN_NODE_FLOOR`) stays, so a lone letter loop or a short word ("hello") is never a node. Above the floor the tests are ratios, so a uniform scale of 1x or 10x gives the same nodes for charts and long handwriting.
- `unattached` keeps the 30 longest strokes (`MAX_UNATTACHED`), returned in id order; `unattached_total` and `unattached_note` report what was dropped. Marker numbers U1.. follow the capped list.
- Marker radius is `round(12 * scale / 2)` clamped to 6..12, font scaled with it, so badges do not cover a zoomed-out sketch.

Known limits: a short word written large (loops over 12 px, fewer than 8 strokes) can still read as nodes; a very short word like "oat" alone can still read as a node; a chart whose nodes are under 5% of the sketch diagonal (about 25+ small nodes in one chunk) loses them. A 6x4 grid of boxes is tested and reads fully.
