# 0047: Draft placement packing and chunker clearance (INK-077)

Status: accepted. Extends 0045.

## Problem
- The gap beside an anchor (about one font size) was smaller than the chunker proximity threshold
  (`k * median element size`, k = 1.5), so an accepted draft would merge into the chunk it sits beside.
- Once the anchor's right and below slots were taken, an op jumped to the scene bottom; unanchored
  ops each went to the global bottom-left. Consecutive drafts ended up far apart.
- `applied` ops kept reserving their estimated box although their real elements were in the scene.

## Decision
- `clear = chunker.proximity_threshold(elements)`; `place` uses `gap = margin = max(old, 1.05 * clear)`.
  Drafts are therefore also separated from each other by more than the threshold: each becomes its own chunk.
- Candidate order: right of anchor, below anchor, below / right of the newest reserving op (column
  packing), then below everything (the fallback that can never overlap).
- `applied` ops use the bbox of their real elements as `recent`; they are not added to `occupied` (the
  scene boxes already are). If the ack raced the autosave and no element exists yet, the estimate is
  reserved. Prefer the newest draft over a same-anchor draft: simple.
- "Near the viewport" is dropped: the server does not know it, and a client-sent hint would be
  untrusted; no-overlap stays server-side.

## Numbers
Tests at ink scale 1 and 10 (stroke 30x40 / 300x400): threshold 60 / 600, draft at least 1.05x that
from every chunk; five consecutive ops stay within `5 * (est_h + 2 * gap)` of each other.

## Trade-off
Drafts sit further from ink than the old 40 px; required by the chunker threshold. Mermaid real size
may exceed the estimate (0032/0045); packing under a pending diagram uses the estimate until acked.
`proximity_threshold` relies on the private `_proximity` returning `(clusters, median)`.
