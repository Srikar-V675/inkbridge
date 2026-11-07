---
name: Inkbridge
description: Warm paper and charcoal carry the app; lime is the agent and nothing else.
version: alpha
colors:
  paper: "#F5F1E8"
  panel: "#EAE4D7"
  pressed: "#DED6C6"
  card: "#FCFAF4"
  charcoal: "#2E2D2B"
  soft-ink: "#625C52"
  lime: "#D4F23A"
  alarm: "#B3261E"
  dot: "#C9BFAC"
  paper-dot: "#D9D1C0"
  pen-charcoal: "#2E2D2B"
  pen-blue: "#2F55B8"
  pen-brick: "#A63D2A"
typography:
  wordmark:
    fontFamily: Instrument Sans
    fontSize: 24px
    fontWeight: 600
    letterSpacing: -0.02em
  title:
    fontFamily: Instrument Sans
    fontSize: 20px
    fontWeight: 600
  reading:
    fontFamily: Instrument Sans
    fontSize: 17px
    fontWeight: 400
    lineHeight: 1.45
  control:
    fontFamily: Instrument Sans
    fontSize: 15px
    fontWeight: 500
  button:
    fontFamily: Instrument Sans
    fontSize: 16px
    fontWeight: 500
  note:
    fontFamily: Instrument Sans
    fontSize: 14px
    fontWeight: 400
  handwriting-stand-in:
    fontFamily: Caveat
    fontSize: 30px
    fontWeight: 500
rounded:
  badge: 6px
  control: 10px
  card: 12px
  rail: 14px
  panel: 16px
  pill: 18px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  touch: 44px
components:
  button-primary:
    backgroundColor: "{colors.charcoal}"
    textColor: "{colors.paper}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: 44px
    padding: 0 18px
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.charcoal}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: 44px
    padding: 0 16px
  button-quiet:
    backgroundColor: transparent
    textColor: "{colors.charcoal}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: 44px
    padding: 0 14px
  button-quiet-hover:
    backgroundColor: "{colors.pressed}"
  offer-chip:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.charcoal}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    height: 36px
  draft-badge:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.badge}"
    padding: 3px 9px
  draft-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.charcoal}"
    typography: "{typography.reading}"
    rounded: "{rounded.card}"
  tool-rail:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.rail}"
    width: 60px
    padding: 8px
  top-bar:
    backgroundColor: transparent
    height: 64px
    padding: 0 20px 0 16px
  side-panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.charcoal}"
    rounded: 16px 0 0 0
    width: 440px
    padding: 18px 24px 20px
  canvas-card:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.card}"
    padding: 16px
  status-risk:
    textColor: "{colors.alarm}"
---

# Inkbridge design system

Source of truth for how the app looks. Derived from the approved mockups (6 Nov 2026, [mockup board](https://claude.ai/artifact/7DHHtPkLuVzYuz4S5qNkDS)); local copy in `docs/tickets/v4-ref/mockups/project/` (untracked). The tokens above are the contract: web code reads them from `web/src/styles/tokens.css`, never hard-coded hex in components. Spec: [`@google/design.md`](https://github.com/google-labs-code/design.md) (alpha); check with `npx @google/design.md lint DESIGN.md`. Regenerate `web/src/styles/tokens.css` with `cd web && npm run tokens` after any front matter change; a test fails if the two drift.

## Overview

Paper, charcoal and one highlighter. Warm paper and charcoal carry the whole app. **Lime is the agent**: anything it wrote, found or is waiting to show you. Nothing else is lime, so you can always tell your ink from its work. The page is a quiet tool for handwriting: chrome stays small, flat and out of the way, and the canvas gets the room.

Proportions: paper and panel 60 percent, charcoal 30 percent, lime 10 percent at most.

## Colors

| Token | Hex | Use |
|---|---|---|
| `card` | `#FCFAF4` | Drafts, home cards, popovers |
| `paper` | `#F5F1E8` | Dotted canvas, page background |
| `panel` | `#EAE4D7` | Tool rail, side panels, secondary buttons |
| `pressed` | `#DED6C6` | Hover and pressed state |
| `charcoal` | `#2E2D2B` | Ink, text, primary button |
| `soft-ink` | `#625C52` | Notes, status, secondary text |
| `lime` | `#D4F23A` | Agent only: offers, drafts, "answer ready" |
| `alarm` | `#B3261E` | Ink at risk only (unsaved in memory), failures |
| `dot` | `#C9BFAC` | Neutral line (card borders on Home) |
| `paper-dot` | `#D9D1C0` | Canvas dots; quieter than `dot` |

Pen colours are the user's own and never lime: charcoal `#2E2D2B`, blue `#2F55B8`, brick `#A63D2A`.

Rules: lime is never used for the user's strokes, selection, focus rings or decoration. Alarm is never decoration. Text on lime is charcoal. Contrast: charcoal on paper, panel and card passes WCAG AA; soft-ink is for 14 px notes and above only (12 px at Small UI size), on paper or card.

## Typography

One family, Instrument Sans (Google Fonts, self-host for the tablet: no network fetch at runtime). Caveat stands in for handwriting in mockups only; the app never renders it.

| Token | Size / weight | Use |
|---|---|---|
| `wordmark` | 24 / 600, tracking -0.02em | Wordmark, home titles |
| `title` | 20 / 600 | Section and thread titles |
| `reading` | 17 / 400, line 1.45 | Answers and drafts |
| `button`, `control` | 16 / 500, 15 / 500 | Buttons, chips |
| `note` | 14 / 400, soft-ink | Notes, status, timestamps |

## Layout

- Canvas first: the canvas fills the viewport; chrome floats over it.
- Top bar 64 px, transparent: Canvases (back to home), canvas title, saved status, Focus, Ask. Zoom control: compact pill, bottom right, 36 px tall visual with a 44 px hit area.
- Tool rail: left, 16 px from the edge (8 px on tablets), 72 px under the top edge on tablets and short screens; capped to the viewport (`100dvh`) and scrolls when still too tall; gaps pack to 0 under 720 px of height. 60 px wide, 8 px padding, 4 px gap: pen, highlighter, eraser, lasso, shapes, text, three ink colours, undo, redo.
- Tablet density: under 1300 px or on a coarse pointer the top bar title is 18 px and status 13 px. Touch targets stay 44 px (decision 0074); visual sizes shrink with the UI size and hit areas stay 44 px (decision 0083).
- Side panel (Ask, threads): right, 440 px, full height under the bar. The canvas does not resize; it pans to keep the working area visible.
- Home: 76 px header with wordmark, search and New canvas; 40 px side margins; Continue card, Recent list, All canvases grid, Archived.
- Spacing scale 4, 8, 16, 24, 40. **Every touch target has a hit area of 44 px or more** (the tablet is the primary device). The visible face scales with the UI size (Small 0.8, Medium 0.9, Large 1.0; default Small on a coarse pointer and Large on a fine one) and a `::after` pseudo-element supplies the rest of the 44 px (the zoom-pill pattern, INK-170), so neighbours' hit areas overlap by up to about 6 px at Small and the later one wins. Inside the shell (`.ink-shell`) every spacing, type and component size is the token value times `--ui-scale` (`web/src/app/uiScale.css`); `--space-touch` is never scaled, type has a 12 px floor, and Home and the Kit are unscaled. 36 px chips only when they sit on the canvas next to ink (INK-177, decision 0083).
- **UI size.** A quiet "Size S/M/L" button in the top bar, left of "Finger draws", cycles Small, Medium, Large and is remembered per device (`inkbridge-ui-scale`). `?ui=0.7` sets and remembers a custom value (0.6 to 1.2); `?ui=0` clears it.
- The canvas background is a CSS dot layer (`paper-dot`, 1 px radius, one dot per 36 scene units, doubled while the gap is under 10 px) that follows pan and zoom, under a transparent Excalidraw canvas. Excalidraw's own toolbar and menus are hidden.
- Shapes flyout and properties card: the Shapes button opens a card of five shape buttons beside the rail; selecting an element, or choosing a shape or text tool, opens a 280 px properties card to the right of the rail (layer 6, above the chunk chips and under the top bar and Ask panel; the flyout paints over it), card colour, radius 12, rows of 44 px options with a `note` label, collapsible to its header; stroke palette is the three pen colours plus soft-ink and dot; pen and highlighter never open it; scrolls when the screen is short.

## Elevation & Depth

Flat. Depth comes from the paper → panel → card steps, not shadows. The one shadow is for floating popovers and toasts: `0 10px 28px rgba(46, 45, 43, 0.16)`. Panels meet the canvas edge with a 1 px `pressed` rule or a rounded corner, never a shadow.

## Shapes

Rounded, never pill-shaped except the offer chip. Radii: badge 6, control 10, card 12, rail 14, panel 16 (outer corner only), offer pill 18. Dashes are for drafts only: a draft's outline is dashed lime; accepted agent text loses the dash and keeps normal ink styling.

## Components

- **Buttons.** Primary (charcoal on paper), secondary (panel), quiet (transparent, `pressed` on hover). 44 px tall, radius 10. One primary per surface.
- **Offer chip.** Lime pill, 36 px tall, 8 px charcoal dot, label such as "Answer ready" or "2 related notes". Sits beside the ink it concerns. Tapping opens a popover (card, popover shadow) with the offer and its actions ("Add links beside loss", "Not useful").
- **Draft.** On the canvas the draft stays a dashed agent-colour outline. The tray at the bottom centre is charcoal with the agent dot, "N drafts on this canvas", Jump, Accept all and Reject all. Selecting a draft shows its card above the tray: card background, dashed charcoal outline, the agent "Draft" badge, a line for the kind ("Text from the agent" or "Diagram from the agent"), a preview of the text, and the actions Accept and Reject; "Open thread" arrives with threads. Accepted and rejected states are the shared card toast (6 s): "Added to your canvas" / "Draft removed." There is no Undo yet (INK-115). Decision 0068.
- **Ask panel.** Side panel: field "Your question" with the hint "To ask about one part, circle it with the lasso first", then "Earlier on this canvas" as thread rows (title, first line, time, "Draft waiting" tag). Send is a round 44 px charcoal icon button; the panel is portalled above the rail and bar.
- **Thread.** You and Agent messages, vault sources as links ("Used from your vault, opens in Obsidian"), draft actions (Show, Draw as diagram, Add to note), follow-up field with Send. Back (not All threads) returns to the list; vault names are plain pills until Obsidian links exist; Draw as diagram and Add to note wait for INK-134.
- **Focus.** A banner "Focus on. Suggestions wait until you turn it off. Ask still works." with a waiting count and Turn off. While on, offer chips are hidden.
- **Saved status.** Quiet by default: a check and "Saved". Saving shows a soft-ink dot ("Saving…"); a merge with another device reads "Merged with another device" with its detail as visible text until the next save; loading shows plain text. Ink that exists only in memory (offline, or a rejected save) shows the alarm dot and "Ink only in memory: do not close this tab" (or the save error's own words). The soft-ink "Kept on this device, sending when the network is back" state waits for the offline outbox, which stores ink on the device; until then a network failure is the alarm state. Decision 0068.
- **Chunk overlay.** The top bar has a quiet "Chunks" toggle left of Ask. Chunk outlines are soft-ink, a pinned (manual) chunk is thicker, a selected chunk is a thick charcoal outline with a light charcoal wash and a partly selected one is dashed charcoal. Each chunk has a charcoal tab with its id, a 44 px target over the top left corner (inside the box when it touches the top edge). Merge chunks and Split selection sit in a card above the zoom control. Never the agent colour (that is the agent) and never a pen colour (that is the user's ink).
- **Touch.** A quiet "Finger draws" toggle sits left of "Chunks" (off by default); a finger pans and pinches, only the pen draws. When on, the toggle is filled charcoal like a pressed rail button; off is the quiet button on every device.
- **Canvas card (home).** Card background, radius 12, 120 px thumbnail, title, "Edited 12 minutes ago, 11 chunks", optional "1 draft, 2 notes" or "Note stale" tag. The thumbnail is a 960 x 640 PNG on the panel colour (shown at 480 x 320), fitted to the ink without far outliers, strokes at least 2 px at card size, never drafts. Decision 0070.
- **Canvas state.** When a canvas does not open, the canvas area shows a centred block on paper: a charcoal title ("Canvas not found" for an unknown id, "Could not open this canvas" for a failed load), one soft-ink line and a secondary "Back to canvases" button. No lime, no alarm colour (the top bar status already carries the failure). INK-172, decision 0071.
- **Properties card.** (INK-175, decision 0075) A card, not a panel: card colour, radius 12, 280 px wide, with the element kind as its title ("Rectangle", "3 selected", "Arrow tool") and a 44 px Collapse button. Rows by element kind, each a `note` label over 44 px options: stroke colour (charcoal, blue, brick, soft-ink, dot), background, fill style, stroke width, stroke style, sloppiness, edges, arrowheads and arrow type, opacity (a slider with a 28 px charcoal thumb), and for text font (Hand, Normal, Code), size (S, M, L, XL) and alignment; a selection adds layers, Duplicate, Delete and Lock. The pressed option is a charcoal fill with a paper icon, as on the rail. Delete is charcoal, not alarm (alarm is only for ink at risk and failures). It never shows for the pen, highlighter or eraser, nor for a selection that holds an agent draft.

## Do's and Don'ts

Do
- Use lime only for what the agent wrote, found or is waiting to show.
- Keep touch targets at 44 px or more and read colours from the tokens.
- Show status only when it matters (saving, risk, failure).
- Keep chrome off the canvas: floating, small and dismissible.

Don't
- Don't draw the user's ink, selection or focus rings in lime.
- Don't use alarm for decoration or non-ink warnings.
- Don't add shadows, gradients or colours outside the table.
- Don't render handwriting-style fonts in the app; agents write text boxes, shapes and diagrams.
- Don't let the chrome resize or reflow the canvas.
