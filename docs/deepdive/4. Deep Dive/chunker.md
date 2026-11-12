# Deep Dive: chunker (`server/src/inkbridge/canvas/chunker/`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

Pure module: no I/O, no SQLite. It runs inside every scene save (`db/chunks.py`, `_sync_chunks`; Updated 13 Nov 2026: the package is split into `clustering.py`, `config.py`, `scene.py`, `matching.py`, `order.py` plus the v2 files below, so the `file:line` references in the v1 sections below point at the old single module and are approximate) and turns Excalidraw elements into **chunks** (lists of element ids) plus **arrow links**, then keeps chunk ids stable across saves.

## Responsibilities

- Cluster live ink by proximity (`cluster` / `_proximity`).
- Apply the arrow rules: short arrows merge two chunks, long ones become links (`chunk_scene`).
- Honour manual overrides (pins, `pin_groups`).
- Order chunks for reading (`reading_order`), guess a kind (`kind_hint`).
- Match new clusters to old chunk ids (`match_chunks`).

## Pipeline

![diagram 1](../../img/chunker-1.png)

<details><summary>Mermaid source</summary>

```mermaid
flowchart TD
  E[scene elements] --> CE[clustering_elements<br/>drop deleted, drafts, arrows, lines,<br/>and labels of non-participating containers]
  CE --> P[_proximity<br/>median size, threshold = k x median,<br/>union-find over a multi-level grid]
  PIN[pins from active pinned chunks] --> PG[pin_groups]
  PG --> P
  P --> G[proximity groups + pinned groups]
  G --> A[chunk_scene arrow rules<br/>end_chunk per arrow end]
  A -->|short, both ends free| M[union the two groups]
  A -->|long or touches a pin| L[link start -> end]
  A --> J[connector + label join the start chunk]
  M --> OUT[Chunking: chunks, links, pinned]
  L --> OUT
  J --> OUT
  OUT --> MC[match_chunks<br/>Jaccard against old chunks]
  MC --> IDS[stable ids, orphans, successors]
```

</details>

## Chunker v2, the default (Updated 13 Nov 2026)

Chunker v2 (INK-122, decision 0081) is the default since INK-195 (decision 0110). `db/chunks.py` `_resolve_config` picks it: `ChunkerConfig.v2()` when the canvas's own `documents.chunker` is `v2` (or unset and `INKBRIDGE_CHUNKER` is not `v1`); v1 stays available per canvas (`PATCH /documents/{id}` with `{chunker}` re-chunks at once) and is pinned by a golden file (`server/tests/data/chunker_v1_golden.json`). `chunk_scene` in `scene.py` dispatches to `chunk_scene_v2` when `config.version == "v2"`. `ChunkerConfig.v2()` sets `k` 2.0, `next_line` 2.0, `arrow_merge` 1.0 and `link_reach` 2.0; `long_stroke` is 4.0 (all in units of T, the writing scale).

Pipeline of `chunk_scene_v2` (`scene_v2.py`):

1. **Stroke kinds** (`canvas/strokes.py`, `analyse` / `classify`, decision 0078). Every live freedraw stroke gets one of `writing`, `container` (a closed loop with ink inside), `connector` (a long smooth stroke, or one with a head, hook or shape at an end), `head` (the small stroke that makes an arrow tip), `underline` (flat, under writing) or `scribble` (a tight zigzag). T is the writing scale (`SCALE_PCT` quantile of the short strokes, floor `MIN_SCALE`), so every threshold is a multiple of T and holds at any zoom. Arrows are decided by length and smoothness (`ARROW_LONG`, `SMOOTH_*`, decision 0118); slanted writing is levelled by its principal axis; scribbles join the writing (INK-195, INK-203). Thresholds are start values awaiting real-page evals.
2. **Exclusions.** Pen connectors, their heads, native arrows and lines and their labels are never chunk members (`stroke_connector_ids`, `connector_ids`), so moving or deleting an arrow changes no chunk hash.
3. **Pins and agent groups** (`pin_groups`, `agent_groups`) are carved out first, as in v1; accepted agent ink is its own chunk.
4. **Line-aware clustering** (`lines.py`, `cluster_lines`): on one line two elements join within `k x T`; on adjacent lines only when their boxes overlap in x and the gap is under `next_line x T`; a stroke longer than `long_stroke x T` joins by its ink (`_samples`, `_ink_below`), not its bounding box, so an arc round a word does not swallow it; a container loop unions what it holds; underlines and scribbles join the writing they touch (`UNDERLINE_REACH`, `_SCRIBBLE_NEAR`).
5. **Oversized split** (`split.py`, `split_oversized`, INK-209, decision 0124): a group over `MAX_SIDE` 3000 units or `MAX_ELEMENTS` 600 (the reader's own limits are 4096 units and 1500 elements) is cut at the widest empty gap on its longer axis, and each part again until it fits or has no gap left. Members that overlap in both axes are never separated. In a group over the caps, bridges (a frame or scribble much bigger than the writing, `_core`) leave first and stand as chunks of their own, otherwise they would keep every gap closed.
6. **Connectors** (`connectors.py`, `EndIndex`, `end_points`): each connector end maps to the bound chunk or the nearest chunk box within `link_reach x T`. A connector whose ends are both free and short (a tick, `arrow_merge x T`) merges the two chunks; a longer one writes a `links` row with `confidence` (`_confidence`); both ends in one chunk make nothing; a connector with a free end becomes a chunk of its own with `kind: connector`, which is never read, and the export skill skips it.
7. **Matching and order** are shared with v1 (`match_chunks`, `reading_order`); the id-stability rules below apply unchanged.

Why this shape: model-based page grouping was tried and dropped (Sonnet grouped well but cost about $0.06 and 39 s per page; Haiku grouped poorly), so grouping is deterministic and the model only reads (README, "How it got here").

Tests: `test_chunker.py` (v1), `test_strokes.py`, `test_chunker_v2.py`, `test_chunker_v2_db.py`, `test_chunker_v1_v2_compare.py`, `test_chunk_split.py`, `test_large_chunks.py`.

## Configuration, v1 values (`ChunkerConfig` in `config.py`)

| Field | Default | Meaning |
|---|---|---|
| `k` | 1.5 | Merge when the gap between two boxes is below `k x median element size` |
| `arrow_merge` | 6.0 | An arrow whose path is at most this many medians long merges its two chunks |
| `link_reach` | 3.0 | A free arrow end links to a chunk within this many medians |
| `min_median` | 4.0 px | Floor for the median, so tiny dots cannot collapse the threshold |
| `match_threshold` | 0.5 | A cluster keeps an old id when element-id Jaccard is above this |

The dataclass is frozen and validates in `__post_init__`: the first four must be positive, `match_threshold` in `[0, 1)`. All constants live in one object so one config tunes the whole pipeline (`test_config_rejects_values_that_break_the_maths`, `test_chunker.py:501`). Decision 0022 kept these values after a synthetic sweep; real handwriting still needs checking.

## Who takes part (`clustering_elements`, `canvas/chunker/:57-75`)

An element clusters by proximity only if it is not deleted, not a draft (`customData.draft`), and not an `arrow`/`line` (`_CONNECTORS`, `canvas/chunker/:19`). Bound text follows its container: if the container is in the scene but does not take part (deleted, draft, or a connector), the text is dropped too, so a draft's label never becomes content (`test_label_of_a_draft_or_deleted_container_is_not_content`). If the `containerId` points at nothing, the text clusters by proximity like anything else (`test_dangling_container_id_clusters_by_proximity`).

## Proximity clustering (`_proximity`, `canvas/chunker/:110-217`)

1. **Order and sizes.** Elements are sorted by id (so input order never matters, `test_result_is_independent_of_input_order`). Each element's size is `max(width, height)` of its box (`_box` uses `bbox_of`, which uses point extents for strokes). `median = max(median(sizes), min_median)`; `threshold = k x median` (lines 118-123).
2. **Pins excluded, but they still count in the median** (line 121-124), so pinning a group does not change how the rest clusters.
3. **Bound text** is unioned with its container directly, at any distance (lines 133-137, `test_bound_text_joins_its_container_regardless_of_distance`).
4. **Identical boxes** (overwritten strokes, stacked shapes) are unioned up front and only the first goes into the grid (lines 153-162, `test_identical_boxes_form_one_chunk_even_when_tiny`).
5. **Multi-level grid** (lines 139-176). Level-0 cells are `threshold / 2` wide. An element is indexed at the finest level where it covers at most `_MAX_CELLS = 64` cells; each further level has cells `_LEVEL_FACTOR = 8` times wider. Oversize elements therefore never fall back to comparing against everything.
6. **Free merge inside a level-0 cell** (lines 178-180): two boxes touching the same level-0 cell are at most `threshold / sqrt(2)` apart (the cell diagonal), so every member of a cell is unioned without measuring.
7. **Neighbour search** (lines 186-212): for each element, per level, the cells within `threshold` of its box are visited. A cell known to hold one group (`single`, lines 183-184) is skipped once its representative is in the same group. Otherwise members after `i` (via `bisect`) are tested with `_gap(a, b) < threshold`, where `_gap` is the Euclidean distance between boxes (0 when they overlap, `canvas/chunker/:94-97`). When a cell becomes single-group it is recorded.
8. **Output** (line 214-217): ids grouped by union-find root, each group sorted, groups sorted by their smallest id; the median is returned too because the arrow step reuses it.

The union-find (`canvas/chunker/:78-91`) uses path halving and always roots at the smaller index, which keeps results deterministic.

Complexity notes in the tests: 5,000 elements cluster in under a second, dense overlapping ink and mixed oversize elements stay fast, and the grid result equals a brute-force comparison (`test_grid_clustering_matches_brute_force_on_mixed_sizes`, `test_chunker.py:209`).

**Worked example.** Strokes of about 20 px: median 20, threshold 30. Two words 25 px apart merge into one chunk; a heading 45 px above the next line stays separate. If lines are 40 px apart with 20 px strokes (gap 20 < 30) they merge into one paragraph chunk, which decision 0022 accepts for notes but flags for re-checking on real pages.

Scaling the whole layout does not change the result (`test_scaling_the_layout_does_not_change_the_clustering`).

## Pins (`pin_groups`, `canvas/chunker/:227-250`)

A pin is a set of element ids from a manual merge or split (INK-059, decision 0024). `pin_groups` reduces pins to ink that can cluster: ids that are deleted, drafts, connectors or unknown are dropped. A container and its bound text are one unit (keyed by the container id), so picking either picks both. Pins are made disjoint, earlier pins keeping a shared unit. Empty pins vanish. Pinned groups are appended after the proximity groups and nothing joins them by proximity.

## Arrow rules (`chunk_scene`, `canvas/chunker/:267-385`)

Each live arrow/line gets two ends via `end_chunk(c, binding, point_index)` (lines 321-343):

1. **Bound end** (`startBinding`/`endBinding`): the chunk that owns the bound element. If that element is in no chunk (deleted or a draft) the end **dangles** (`None`), it does not fall through to geometry.
2. **Free end**: the end point is `x + points[i]` in canvas coordinates. A non-finite point dangles. Candidates come from a uniform grid of `reach`-wide cells (`reach = link_reach x median`), searching the 3 x 3 cells around the point, plus `large` boxes that span more than `_MAX_CELLS` cells. Among candidates the nearest box wins; ties between nested boxes go to the smaller area (`scored` tuple, line 336-340). Farther than `reach` means dangling.

Then (lines 345-358): an arrow with at least two points whose path length is at most `arrow_merge x median` and whose ends are both free and not in a pinned chunk (`max(start, end) < first_pinned`) merges the two groups (`uf.union`). Otherwise, if it is an arrow, it is recorded as a possible link. Lines (`type: line`) never merge or link. Short arrows merge transitively (`test_short_arrows_merge_transitively`).

Finally (lines 360-374): every connector and its bound label join the chunk of its **start**, else of its **end**; with neither it forms a chunk of its own (`extra`). A link `(find(start), find(end))` is added only if the two roots differ after merging, so arrows inside one chunk or into a merged chunk make no self-link.

Result (`Chunking`, lines 377-385): chunks sorted by smallest member id, `links` as sorted unique index pairs, and `pinned` flags (root index at or beyond `first_pinned`). The `links` direction follows the arrow (`test_link_direction_follows_the_arrow_and_duplicates_collapse`).

## Reading order and kind

- `reading_order(boxes)` (`canvas/chunker/:399-419`): sort by `(y, x, id)`, then group into rows; a chunk joins the current row when its vertical centre is within `0.5 x median chunk height` of the row's mean centre. Rows read top to bottom, each left to right, so a slightly slanted left-to-right diagram reads left to right (`test_reading_order_row_tolerance_reads_a_slanted_diagram_left_to_right`).
- `kind_hint(elements)` (`canvas/chunker/:422-431`): `handwriting` when no shapes, `diagram` when shapes and no `freedraw`/`text`, else `mixed`. A hint only, ignores drafts. The Gemini reading may later overwrite `kind` (`db/__init__.py:932-946`).

## Stable ids (`match_chunks`, `canvas/chunker/:440-502`)

Inputs: every old auto chunk of the canvas (orphaned too, so undo can reactivate one), the new clusters, their top y values, the set of active old ids, the threshold, and an `ignore` set.

- **Core**: connectors and their labels (`connector_ids`, line 388) are removed before comparing, so drawing or deleting an arrow does not change a small chunk's id. A chunk made only of ignored ids is matched on all of them.
- **Candidates**: via an element-to-old-chunk index, count shared elements per (cluster, old chunk) and compute `J = inter / (|new| + |old| - inter)`. Pairs with `J > threshold` are kept.
- **Greedy one-to-one**: sort by `(-J, -overlap, orphaned-last, old id, cluster index)` and assign each pair if neither side is taken. So the highest Jaccard wins, a larger overlap breaks ties, and an active chunk beats an orphaned one.
- **Successors**: every active old chunk left unmatched is orphaned; its successor is the cluster sharing the most elements (ties: higher on the page, then lower index), or `None` if it shares nothing (a deleted chunk).

Consequences, all covered in `test_chunker.py:314-400`: adding a stroke keeps the id; a half-and-half split gives both pieces new ids with the higher piece as successor; an uneven split keeps the id on the big piece; a merge gives a new id and both old ids point at it; undo hands an orphaned chunk its id back. The known weakness is small chunks: two elements gaining three is J = 0.4 and gets a new id. The safety net is `check_sync`, which reports `replaced` with the successor.

## How `db/__init__.py` uses it

`_sync_chunks` (`db/__init__.py:463-556`) feeds pins from active pinned chunk rows, calls `chunk_scene`, computes bounding boxes, calls `match_chunks(... ignore=connector_ids(elements))`, creates uuid ids for unmatched clusters, then upserts. See [database.md](database.md).

## Testing

`server/tests/test_chunker.py` (pure unit tests, including a brute-force comparison and speed checks), `test_chunk_pins.py`, `test_links.py` and `test_chunk_persistence.py` (database level, including a 2,000-element scene and rollback).

## Potential improvements

- Small-chunk identity: Jaccard loses ids for chunks of one or two strokes. Decision 0022 considers a 60% containment test but rejects it for now because merge/split would be ambiguous.
- `k` has not been tuned on real handwriting (decision 0022); line spacing under 1.5 median merges paragraphs.
- Rows in `reading_order` use a mean centre, so a very tall chunk can pull neighbours into its row.
