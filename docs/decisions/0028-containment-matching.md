# 0028: containment matching for chunk ids (flag, off by default)

Status: accepted (INK-072)

## Problem

`match_chunks` keeps a chunk's id when the element-id Jaccard with a new cluster is above 0.5
(decision 0011). Small chunks are fragile: 2 strokes that gain 3 have J = 0.4 and lose their id; a
50/50 split (J = 0.5, strict threshold) gives both halves new ids. A lost id orphans the chunk, so
a vault note sees `replaced` (or `removed`) for what the user experiences as the same writing.

## Change

`INKBRIDGE_CHUNK_CONTAINMENT` (a fraction in (0, 1], for example 0.6; unset or 0 = off) adds a
second way for a pair to qualify: at least that share of the old chunk is inside the new cluster,
or at least that share of the new cluster came from the old chunk. Pairs still sort by Jaccard
first, so a containment-only pair never takes an id from a better Jaccard match. `match_threshold`
is unchanged. Wiring: `config.chunk_containment()` -> `ChunkerConfig.match_containment` ->
`match_chunks(containment=)` in `_sync_chunks`; an explicit `ChunkerConfig` wins over the env var.

## Evaluation

`scripts/chunk_identity_eval.py`: pure `match_chunks` over synthetic edits of a chunk of n strokes
(n = 2, 3, 4, 6, 10, 20). Each cell shows three letters for off / 0.6 / 0.75 (K = the id is kept,
. = new id). For `rewrite` and `unrelated` a K is wrong.

```
case               n=2   n=3   n=4   n=6  n=10  n=20   (off / 0.6 / 0.75; K=kept, .=new id)
grow+1             KKK   KKK   KKK   KKK   KKK   KKK
grow+2             .KK   KKK   KKK   KKK   KKK   KKK
grow+3             .KK   .KK   KKK   KKK   KKK   KKK
grow+4             .KK   .KK   .KK   KKK   KKK   KKK
grow+5             .KK   .KK   .KK   KKK   KKK   KKK
shrink-1           .KK   KKK   KKK   KKK   KKK   KKK
split 50/50        .KK   ...   .KK   .KK   .KK   .KK
split 70/30        .KK   KKK   KKK   KKK   KKK   KKK
merge equal        .KK   .KK   .KK   .KK   .KK   .KK
merge big+small    KKK   KKK   KKK   KKK   KKK   KKK
rewrite 50%        ...   .K.   ...   ...   ...   ...
unrelated          ...   ...   ...   ...   ...   ...
shrink-2             -   .KK   .KK   KKK   KKK   KKK
shrink-3             -     -   .KK   .KK   KKK   KKK
shrink-4             -     -     -   .KK   KKK   KKK
shrink-5             -     -     -   .KK   .KK   KKK

variant  should keep  kept  wrongly kept  (of 87 cases)
off               75    45             0
c0.6              75    74             1
c0.75             75    74             0
```

Reading it:
- Off keeps 45 of the 75 cases that should keep the id. 0.6 and 0.75 keep 74. Both fix grow and
  shrink for every n up to 4, the 70/30 split, and merge-of-equals (the old id continues in the
  merged chunk; before, a merge always renamed).
- The one miss in both is the 50/50 split of 3 strokes (1 of 3 is 33% of the old chunk).
- Cost: at 0.6 a rewrite of one stroke in three (67% of the old ink survives) keeps its id; at
  0.75 no rewrite or unrelated cluster keeps an id (0 wrongly kept). Rewrites that keep at least
  half the strokes are what the threshold is meant to treat as the same chunk, but 0.75 is the
  conservative setting.

## Decision

Ship the flag off. When it is turned on, ids that used to change now persist, so `check_sync`
outcomes change for existing notes (`replaced` becomes `changed` or `fresh_after_reread`): that is
why it is not the default. Recommended value once confirmed: 0.6 (the figure in decision 0011);
0.75 if rewrites keeping their id turn out to matter. The data is synthetic: re-run
`scripts/chunk_identity_eval.py` against E5 pages (INK-061) before turning it on.
