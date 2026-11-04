# 0045 Agent text scale: one ink_scale, no 64 clamp

Status: accepted (INK-082). Supersedes 0032 items 1 and 2.

## Problem
Text written at 10x handwriting stayed tiny and its size drifted between ops. Two causes, found by reading the code:
1. `font_size_for` clamped to 18..64 and the client `opFontSize` clamped again to 200. Strokes of height 200 gave 64 (old) instead of 450 (new).
2. The sample was the anchor chunk's strokes, else every stroke on the page in file order. A sparse or mega-chunk anchor swung between samples from one op to the next.

## Decision
- ink_scale = median stroke height of the anchor chunk's live user strokes; with fewer than 3, the latest 50 live user strokes in scene order (write order). Agent and draft strokes never count. Fewer than 3 overall: `DEFAULT_FONT`.
- `font = round(scale * INK_TO_FONT(1.5) * hint)`, bounded only by `MIN_FONT = 18` and a sanity `MAX_FONT = 2000`. 1.5 is still a tablet-tuning guess (strokes are words).
- Gap and margin scale with the font: `gap = max(40, fs)`, `margin = max(16, 0.4 * fs)`; identical to before at fs <= 40.
- The server also stores `wrap_chars = 50`; the browser wraps text at that many characters (`wrapText`) and the size estimate uses the wrapped line count. Like `font_size` it is server-only (payload models forbid it) and excluded from the idempotent-retry comparison. Legacy ops without it estimate unwrapped.
- No ack protocol change: applied drafts are real scene elements (persisted before the ack), so placement sees real sizes afterwards; only the pre-ack estimate matters and it now scales with `fs`. Accept never touches `fontSize` (test in `resolve.test.ts`).
- Mermaid real size can still exceed `DIAGRAM_SIZE * fs / 20` (accepted, as 0032 item 5).

## Numbers (synthetic, from the tests)
Strokes of height 20 / 200: old font 30 / 64, new 30 / 300; old gap 40 / 40, new 40 / 300.
Sparse anchor on 2 tiny strokes with 60 large strokes elsewhere: old page-wide median in file order, new median of the latest 50.
