# 0054: Bring a new agent draft into view (INK-076)

Status: accepted

## Context
An agent draft lands wherever placement puts it, and the user kept hunting for it. The first-draft
fit from decision 0019 only covered an empty canvas, and `scrollToContent` with `fitToViewport`
also changes the zoom. The user writes at about 10x, so a zoom change is as bad as a jump.

## Decision
- **Pan only, never zoom.** A draft that is off-screen moves the scroll position; the zoom is never
  passed to `updateScene`. `scrollToContent` is not used for drafts.
- **Visible** means at least half of the draft's box is inside the viewport, or at least half of
  the viewport when the box is larger than the view. The viewport is in scene units at the current
  zoom (screen = (scene + scroll) * zoom). The test lives in `web/src/draftView.ts`, which has no
  Excalidraw import and is covered by node tests, including a 10x case.
- **Reveal policy** for a freshly drawn op (`web/src/App.tsx`, `reveal`):
  - in view: nothing;
  - off-screen, pen up, and no pan in the last 1500 ms: pan to centre the draft; a draft larger than
    the view puts its top-left at a 40 px screen margin;
  - off-screen and (pen down, or a pan happened within 1500 ms in the same batch): add the op to an
    "unseen" set and show a "New draft, jump" chip in the DraftBar.
- **Pen state** comes from `appState.cursorButton === "down"` or a non-null `newElement`, read on
  every change event before any early return, so a stroke in progress never causes a pan.
- **The chip** pans to the oldest unseen draft (zoom unchanged) and removes it. A draft the user
  brings into view by hand, or one that is accepted or rejected, leaves the set too. The user may
  ignore the chip.
- **Replaces the INK-043 first-draft fit.** `fitFirstDrafts`, `armedView`, and
  `keepFittingFirstDrafts` are removed. Only one mover remains.
- **Out of scope:** general next-draft stepping. The chip steps through unseen drafts, which covers
  batches.

## Consequences
- Drafts far apart (INK-077 placement not yet fixed) produce a chip each beyond the first pan. This
  is accepted until placement is fixed.
- A stroke started between the draw and the reveal is caught by the pen-down read at reveal time.
- Drafts and ops are never modified; this is view-only, so no invariant is touched.
