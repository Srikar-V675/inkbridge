# 0119: Latest ink reads only the newest cluster (INK-204)

Status: accepted, 11 Nov 2026. No migration. Amends 0117.

## Context

Owner test after INK-202: "2+2=" gave no offer. Saves arrive in bursts (65 to 89 strokes), the
whole batch was cropped, so the model read half the page; a scene change during the call dropped
the result and the same growing batch was retried at once (45 calls in minutes); and the anchor was
the chunk holding most of the batch, the big page chunk.

## Decision

- `newest_cluster`: order the batch by element `updated`, start at the newest stroke, add strokes
  whose box is within 2x the median stroke size (floor 10) of the cluster box and whose `updated` is
  within 10 s of the newest, at most 25. The crop is that cluster only; the watermark moves past the
  whole batch, so the rest is skipped. Without `updated` the distance rule alone applies.
- No loop: at least 6 s between reader calls per document, at most 8 per minute and 60 per hour
  (in-memory, `clock` injectable). A throttled or dropped look keeps the watermark and `scan_now`
  schedules another scan (debounced, and gated by the quiet window again). The hour cap gives the
  batch up (mark moves) so it cannot retry for ever. Capped looks are logged (`outcome=capped`).
- Anchor: the smallest active chunk whose box holds the cluster centre, else the nearest.
- Offer text longer than 200 chars means the crop was wrong: logged `too_long`, no offer.
- Prompt: "2+2=" with no answer is an equation, "What is X?" a question; ask for the text only.
- All numbers are hypotheses to tune from the log (`strokes`, `text_len`, `calls`).

Owner check: write "2+2=" on a busy page; expect `strokes <= 25`, `text_len < 60`, one equation offer
on its own chunk.
