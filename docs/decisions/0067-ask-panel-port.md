# 0067: Ask panel port

Status: accepted (INK-161). Owner checks pending: visual match of the Ask and Thread boards on the tablet and laptop, an ask with a lasso selection on the real canvas (open the thread, follow up, Keep on canvas, see the draft), a runner failure line in a row and in the thread, the panel covering the zoom control, the draft bar, the merge/split stack and the Show-chunks toggle while open (with the panel closed, Keep on canvas drafts can be accepted).

## Context

The v4 Ask and Thread boards replace the pre-v4 floating panel. The old panel was a child of `.ink-shell__canvas`, whose `z-index: 1` makes its own stacking context, so the rail, top bar and zoom control (z-index 5, decision 0066) painted over anything inside it.

## Decision

- **Portal, not a Shell slot.** `AskPanel` keeps its props `{api, canvas, open, onClose}` and renders through `createPortal` into `.ink-shell` at `z-index: 8` (above the INK-162 overlays layer at 6 and the top bar at 7; it starts below the bar, so the bar and Ask button stay reachable). This escapes the canvas stacking context for this panel only, and avoids the Shell and App registration line that INK-162 and INK-118 also edit. Chips that sit under the rail stay with INK-162. The panel is `position: absolute` from `--component-top-bar-height` to the bottom, so the canvas does not resize and the Ask button stays reachable.
- **The open panel (z 8, full height below the top bar, 440 px) covers the zoom control and anything of the INK-162 overlays layer (draft tray and card, merge/split card, chunk tabs) that lies in its 440 px strip.** The draft tray is bottom centre and the Chunks toggle is in the top bar, so on a 1280 px screen they stay reachable. Keep on canvas's "accept it on the canvas" hint therefore needs the panel closed first. DraftBar and ChunkOverlay are not edited here because INK-162 rewrites them.
- **The zoom control is covered too.** The canvas does not pan to keep the working area visible; DESIGN.md mentions that, but it is not in this ticket.
- **Threads are derived on the client** from `parent_id` (`ask/threads.ts`): a root plus its follow-ups, newest activity first, items oldest first. A follow-up whose parent is not in the list becomes its own root, and a parent cycle terminates. No server change.
- **List rows** show the root question as the title and the state of the latest question as the line (runner failure in the alarm colour, "Waiting for an agent", "Cancelled", or the first line of the answer with markdown stripped), then a relative time.
- **The per-answer "Follow up" button became the thread's follow-up field.** A new question from the list opens its own thread. A follow-up still sends the current selection, so with none the server inherits the parent's focus (decision 0061).
- **Send still needs a selection in the list view.** The board's "About what is on screen" is not adopted because the old gate stays ("no new behaviour"); allowing an empty-focus ask is an owner decision (the API already accepts it).
- **"Back" instead of "All threads".** That navigation waits for INK-134, but a thread view with no way out would be a dead end.
- **Vault names are plain pills, not links**: there is no Obsidian link data yet. Only the file name is shown (decision 0046).
- **Panel state survives navigation.** Half-typed text is kept per view (list, or each thread) so Back does not discard it, and "kept" (Keep on canvas done) is held at panel level by question id so reopening a thread cannot allow a second draft click. List row lines are memoised over the threads.
- **Left out until INK-134:** "Draft waiting" tag, "Draw as diagram", "Add to note".
- **Colour.** Lime is absent from the panel (it means the agent only); the Agent label carries an 8 px charcoal dot. The kit's secondary button is panel-coloured and vanishes on this panel, so `ask.css` gives it the card colour as the boards do. Alarm colour is used for runner failures and send errors only.
- **Tests.** No DOM harness exists (decision 0046): logic is in `threads.ts` (Node tests), and `askPanel.test.ts` checks the stacking, portal, no-lime, no-hex and no-raw-button rules from source. `ask/AskPanel.tsx` left the design-rules LEGACY list because it no longer holds hex.

## Consequences

If INK-162 or INK-118 renames `.ink-shell` the panel renders nothing; `askPanel.test.ts` names the selector. `.ink-ask { padding: 0 }` overrides the `Panel` padding token, so a change to `ui/Panel.css` specificity would double the head and body padding.
