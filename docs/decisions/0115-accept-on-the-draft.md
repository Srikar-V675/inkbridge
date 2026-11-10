# 0115: Accept and reject each draft where it sits

INK-200. Status: accepted.

## Context

Owner, 10 Nov: with two drafts on the canvas the only buttons were "Accept all" and "Reject all".

## Cause

`DraftBar` rendered the per-draft card (Accept, Reject) only for a draft that was the single one or had an Excalidraw element selected. With two or more drafts and nothing selected the card list was empty and only the tray showed. Not hidden: never rendered.

## Decision

- Every draft in view gets a small pill at its top-right corner with Accept and Reject (`DraftPills.tsx`), no selection needed. It follows pan and zoom (`followScroll`) and moves when a draft is dragged.
- Placement is pure and tested in `draftPills.ts` (`pillPosition`): above the top-right corner, flipped below when there is no room, clamped inside the free area clear of the top bar, rail and tray. Off-screen drafts get none.
- The card stays for a selected draft (preview, Open thread); a single draft no longer auto-shows it (`cardOpIds`).
- The tray keeps Jump; Accept all and Reject all show only for two or more drafts (`showBulk`).
- Accept and reject use the same idempotent endpoints and store updates as before, so accepting one draft leaves the others and lowers the tray count.
- The pill is card colour with a dashed charcoal outline and charcoal buttons; no lime, no new tokens.

## Consequences

- Off-screen drafts have no pill; the New draft chip and Jump cover them.
- A pill for a draft larger than the view is clamped into the free area and may sit over the draft.
- The pill size is an estimate (232 x 52 at UI scale 1), so the clamp can be a few px off.
- Tablet check pending: reaching the pill with the pen and clearance from the rail and tray.
