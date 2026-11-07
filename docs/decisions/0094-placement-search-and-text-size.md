# 0094: Placement search and text sized from line height (INK-116)

Status: accepted. Supersedes 0032, 0045 and 0047 in part.

## Decision
- `place()` scores candidates instead of walking a fixed order. Candidates: 5 rings (1, 1.5, 2.5, 4, 6
  gaps) x 8 directions around the anchor (E first), slots beside nearby boxes, a grid over the view
  when there is no anchor, and the column under the newest draft. Overlapping slots are dropped.
- Score (lowest wins, ties by x then y, so it is deterministic): `1.0 * distance/fs + 3.0 * outside-view
  fraction + 2.0 * crosses a connector + 0.5 * direction penalty - 1.0 * same x as the newest draft`.
  Direction penalty E 0, SE 0.1, S 0.2, SW/NE 0.4, W 0.6, NW 0.7, N 0.8. Weights are starting values.
- "Below everything" is the only fallback, when no candidate is free.
- The view (`attention` frame, INK-130) is advisory: it ranks free spots only. A wrong hint gives a worse
  spot, never an overlap. This reverses 0047's objection to a client hint, which was about trust.
  Format assumed until the web sender ships: `x, y` scene origin, `width, height` screen px, scene rect
  `(x, y, width/zoom, height/zoom)`.
- Clearance (0047) is dropped: accepted agent ink is excluded from proximity (INK-078), so a draft needs
  only `gap_for` / `margin_for`.
- Font = 0.75 x the median distance between lines of the anchor's writing (strokes grouped by centre
  within half the median height; needs 3 strokes and 2 lines). Fallback 1.0 x median stroke height
  (was 1.5). The ticket said about 0.8; 0.75 keeps the INK-095 fixture (height 250, pitch 420, font 315)
  inside 0.7 to 1.3 x letter height.
- `wrap_chars = clamp(int(view scene width / font), 8, 34)`, 34 with no view (was a constant 50).
- `canvas_text` (card text cap) does not exist on this base, so it is not capped here.

## Check left
Owner: tablet look at real pages (font reads at the size of the writing; drafts land beside the chunk).
