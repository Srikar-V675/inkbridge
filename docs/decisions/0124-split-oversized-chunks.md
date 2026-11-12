# 0124 Chunks over the reading limit are cut at their widest gaps

Status: accepted (INK-209). Extends [0052](0052-large-chunk-crop-budget.md) and [0081](0081-chunker-v2.md).

## Problem

On the `default` canvas the v2 chunker made one chunk of 258 elements, 10419 x 9277 units, so the reader returned `too_large` and nothing on that page could be asked or exported. Cause: a 10282-wide scribble and two big frames bridged every gap between the islands of writing.

## Decision

- `canvas/chunker/split.py`, run on the line clusters in `chunk_scene_v2` before arrows merge chunks. A group over `MAX_SIDE` 3000 units or `MAX_ELEMENTS` 600 is handled; smaller groups are untouched, so pages that already chunk well (the `df4730c05e00` note: 27 chunks before and after) do not change.
- Bridges (an element more than 8 times the median side and over 1000 units) leave the group and become chunks of their own; the rest is cut recursively at the widest empty gap on the longer axis until each part fits or has no gap. Members that overlap are never separated.
- Pinned (manual) and agent groups are not split.
- Measured on the live `default` canvas: 11 chunks (one 258-element, 10419 wide) became 33, the largest readable chunk 2832 units, bridges alone in their chunk (unreadable, as before).

## Limits

The caps are fitted to one canvas. A giant frame drawn around a diagram now sits apart from its contents when the group was oversized.
