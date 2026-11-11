# 0118: Long smooth strokes are arrows; everything else clusters by stroke size

INK-203. Status: accepted. Supersedes in part 0110 item 2 (a long straight stroke is a connector only with evidence) and 0078's evidence rule. Numbers are start values for E5.

## Context

On the owner's mind-map page (private dump, 141 freedraw strokes) 0110 item 2 turned every bare long stroke into writing, so the arrows stayed in the cluster: v2 gave 6 chunks with top sizes `[115, 17, 1, 1, 1]`, a 115-stroke blob holding most of the page.

## Decision

- Long = stroke diagonal over `ARROW_LONG` (3.0) times the median stroke diagonal. Arrow shaft = long, straight (net/L over 0.55) or hooked, and smooth: after resampling every 0.3 median diagonals, at most 2 turns sharper than 1.2 rad and total turning at most 6 pi. A shaft needs no head, hook or shape. Cursive words are long but wiggly (16 to 21 pi turning on the real page) so stay writing. Shorter strokes keep the 0110 evidence rule (head, hook, shape).
- A flat stroke with writing above it is still an underline first; a stroke that closes on itself (net under `CONTAINER_CLOSE` of its diagonal) is never a shaft.
- Containers: `CONTAINER_CLOSE` 0.25 to 0.65 and `CONTAINER_LOOP` 1.8 to 1.5, so an outline that does not quite close still holds its ink (the list outline had net/L 0.38).
- v2 clustering: a scribble joins writing within 0.8 T (was overlap only), because cursive words such as "code" read as scribbles and stood alone as 1-stroke chunks.
- Heads are still claimed by `_find_head` (2 strokes after the shaft). Writing direction: v2 clustering never assumed horizontal lines (next-line joins need only a small vertical and horizontal gap), pinned by a synthetic two-line sentence at 0, 20, 25 and 30 degrees staying one chunk.

## Consequences

Real page, before and after (`/tmp/claude-1000/ink203/before.png`, `after.png`; not in the repo): chunks 6 to 6 but now the right six, top sizes `[115, 17, 1, 1, 1]` to `[48, 24, 18, 17, 15]`, 9 connector strokes (were 4), 1 head, 6 links. Boxes:

1. "I'm working on the VS code extension" (slanted, 17 strokes): one chunk, matches. Holds one stray arrowhead.
2. "Now we are extending to CLI & VS Code extension" (24): matches; the long cursive words stay inside.
3. "Ascend Desktop" with its wavy underline (9): matches.
4. "Main framework" + the Goose box + "?" (18): matches; the box outline is a container holding "Goose", the dots below join it. Holds one unclaimed head (V).
5. "+ Deloitte's flavour" (15): matches; one unclaimed head (V) inside.
6. "It has:" list with its outline (48): matches, the only large chunk.

Links: Ascend Desktop to all five others, plus Goose box to Deloitte. Still imperfect: arrowheads drawn more than 2 strokes after their shaft stay writing and sit in a chunk (3 on this page); not widened (`HEAD_ORDER`). A very wavy or looped hand-drawn arrow reads as writing; a smooth long dash reads as an arrow.

Other dumps (counts only): default 11 to 10, 3c2bdf98ac90 68 to 54, f3e2ed44f2d7 6 to 7; none worse by more than 10.
