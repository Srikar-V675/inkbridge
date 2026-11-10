# 0107: Offers audit (INK-184)

Status: accepted. Follows 0089, 0091, 0104, 0105.

## Why offers did not fire

1. **Bug: dangling arrow under chunker v1.** `_dangling` only looked for `kind == "connector"` chunks, which exist only under chunker v2. The default is v1 (0106), so no dangling-arrow offer could ever appear.
2. **Missing visibility.** `detectors.run` swallowed `BudgetFull`, `KindMuted` and `AnchorUnknown`, and `offers.flush` returned silently on Focus, no attention frame, pen down and the quiet window. Nothing was logged, so an empty scan could not be diagnosed.
3. **Not fixable in a detector: no reading.** `question`, `open_equation` and `stale_note` need a chunk reading. With the reader off, a Gemini 429 (0105) or no fresh crop, they cannot fire. The scan log now says how many chunks are unread.
4. **Pen-drawn flowchart.** `sketch` was only tested with native boxes. A new test with freedraw loops and hooked freedraw arrows passes, so no threshold changed.
5. **Gate.** `Attention.can_push` is false until the browser sends one frame (it does on connect). Correct, but now logged.

## v1 free-end arrow rule

`_free_end_arrows` scans the stored scene: a live native arrow (not deleted, no `customData.draft`) with no `endBinding` whose tip is more than `DANGLE_TOL` (40 scene units) from every non-arrow, non-line element's axis-aligned box. Anchor: the chunk that owns the arrow, else the chunk of its `startBinding`; an arrow with neither is skipped (debug log). The key is the arrow id. One `dangling_arrow` candidate per anchor, so a v2 connector chunk and a scene arrow do not both fire.

## Log lines (logger `inkbridge.offers`, INFO)

- `scan doc=D chunks=N unread=M candidates=K {kind: n}`: chunks the scan sees (agent chunks excluded), how many have no reading, candidates by kind.
- `detector run doc=D candidates=K created={kind: n} skipped={"kind:budget_full"|"kind:kind_muted"|"kind:anchor_unknown": n}`.
- `offers held doc=D reason=focus|no_attention|pen_down|quiet_<s>s`: why `flush` pushed nothing.

Read them on stderr when a chip is missing: `unread` equal to `chunks` means no reader; `held` means the gate; `skipped` means budget or mute.

## Shortcuts

- Rotation is ignored in the tip-to-box distance; `DANGLE_TOL` is a start value to tune on real pages.
- `scan` runs twice per `scan_now` (once for the count line); cheap, revisit if logs show cost.
- Every tapped kind already made a task (`OFFER_MODE`); tests pin sketch to diagram, dangling_arrow to link, others to question. No web change.
