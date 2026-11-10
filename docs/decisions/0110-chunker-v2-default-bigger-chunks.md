# 0110: Chunker v2 stops shattering handwriting and becomes the default

INK-195. Status: accepted. Supersedes in part 0106 ("default stays v1"), 0078 ("a remaining shaft is a connector") and the v2 start values of 0081.

## Context

Measured on three real canvases (private dumps, counts only; non-deleted elements) with `eval/chunker_measure.py`:

| canvas | v1 chunks | v2 before | v2 after | v2 target |
|---|---|---|---|---|
| default | 7 | 208 | 11 | <= 15 |
| 3c2bdf98ac90 | 34 | 143 | 68 | <= 68 |
| f3e2ed44f2d7 | 2 | 26 | 6 | <= 6 |

Three causes, largest first:

1. `clustering._cap` cut a group wider than `max_extent * own median` at its largest gap. When a page-sized curly stroke overlaps everything every gap is <= 0 and the recursion cut down to singletons (`default`: 208 chunks from 12 groups).
2. `strokes.analyse` called every long straight freedraw a connector, evidence or not: 71 / 109 / 14 strokes, so handwriting with a long stroke lost those strokes to connector chunks.
3. v2 writing proximity was too tight for big handwriting: T is below v1's median, a line below joined only with x overlap, strokes over 2 T joined only by ink distance.

## Decision

Changes, each with the counts (default / 3c2 / f3) after it, measured in order:

1. `_cap(..., split_overlapping=False)` for v2 only: with no real gap (best gap <= 0) the group stays whole. v1 keeps the old cut (golden unchanged). 208 / 143 / 26 -> 15 / 143 / 26.
2. A long straight stroke is a connector only with evidence: a head, a hook, or an end within 0.75 T of a native shape (rectangle, ellipse, diamond, frame) or of a container stroke. Otherwise it is writing. Native arrows and lines stay connectors. -> 15 / 135 / 21. Connector strokes 71 / 109 / 14 -> 31 / 58 / 8.
3. `_threshold`: a line below joins when the vertical gap is under `next_line * T` and the horizontal gap under `k * T` (a diagonal neighbour), not only on x overlap. -> 15 / 127 / 19.
4. `ChunkerConfig.long_stroke` 2.0 -> 4.0 (a stroke joins by its ink only above 4 T). -> 15 / 119 / 17.
5. `strokes._scale`: T is the 60th percentile of the short strokes, not their median (`SCALE_PCT`). -> 14 / 106 / 16.
6. `ChunkerConfig.v2()`: `k` 1.5 -> 2.0, `next_line` 0.5 -> 2.0. -> 11 / 68 / 6. Tried `next_line` 3.0: 62 / 10 / 5, but it fused a container test and the 5000-element timing test, so 2.0 stays. The flowchart tests (boxes separate at gap >= 200) stay green.
7. The default flips: `INKBRIDGE_CHUNKER` unset or empty means `v2`; an invalid value warns and means `v2`; `v1` still selects v1. `documents.chunker` NULL follows `config.chunker()`; `PATCH {"chunker": "v1"}` and `"default"` still work.

Final measurement (v2 default settings):

```
3c2bdf98ac90 T=100.4 v1=34 v2=68 v2_connector_chunks=2
default      T=80.5  v1=7  v2=11 v2_connector_chunks=0
f3e2ed44f2d7 T=50.2  v1=2  v2=6  v2_connector_chunks=0
```

Free-end connector chunks are 2 / 0 / 0, within the number of arrows with evidence.

## Consequences

- Thresholds are still start values for E5; they were tuned on three pages and may overfit. Guards: `test_two_paragraphs_a_screen_apart_stay_two`, the flowchart tests and the v1 golden.
- The v2 no-cut guard can leave one very large chunk when a single giant stroke spans two ideas (`default` has a 261-element chunk). The `too_large` budget (decision 0052) keeps it from being read or exported as an image.
- Tests that were written against v1 run with `INKBRIDGE_CHUNKER=v1` set by an autouse fixture in `tests/conftest.py`; tests of the default `delenv` it.
- Owner step, no migration: canvases with an explicit `v1` need `curl -X PATCH :8000/documents/<id> -H 'content-type: application/json' -d '{"chunker":"default"}'`.
- Owner checks: fewer, larger chunk labels on the three real canvases on the tablet; offers still appear; the reader backlog is small.
