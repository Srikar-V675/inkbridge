# 0004: Chunks replace manual regions as the default unit

Status: accepted (INK-028)

- You write on one large canvas per topic, so boxing every group by hand does not scale. The server proposes
  **chunks** after every scene save and stores them in the existing `regions` table with `created_by='auto'`;
  hashing, recognition, search, staleness and images work on them unchanged.
- Clustering (`chunker.py`): union-find over element boxes, merging when the gap is below `k` times the median
  element size (`k = 1.5` to start, floor 4 px; tuned on real pages in INK-038). Bound text joins its container
  directly. Arrows do not cluster by proximity: a short arrow merges its two chunks, a long one becomes a
  `links` row (`arrow`), a dangling one is ignored.
- Chunk ids stay stable when ink is added (greedy one-to-one match on element-id Jaccard > 0.5). A split or
  merge orphans the old chunk and sets `successor_of` to the chunk with the most overlap.
- Agent drafts (`customData.draft`) are excluded from chunking until accepted.
- Manual regions stay valid for focus and as an override (merge/split): a manual region wins over an automatic
  chunk on the same elements. The old plan of "no auto-segmentation" is retired.
- Known failure cases (to be measured as E5): late strokes, crossing connectors, strokes straying from their
  object, and small chunks losing ids at the Jaccard threshold.
