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

Source of truth for how the app looks. Derived from the approved mockups (6 Nov 2026, [mockup board](https://claude.ai/artifact/7DHHtPkLuVzYuz4S5qNkDS)); local copy in `docs/tickets/v4-ref/mockups/project/` (untracked). The tokens above are the contract: web code reads them from `web/src/styles/tokens.css`, never hard-coded hex in components. Spec: [`@google/design.md`](https://github.com/google-labs-code/design.md) (alpha); check with `npx @google/design.md lint DESIGN.md`.

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
| `dot` | `#C9BFAC` | Canvas dots |

Pen colours are the user's own and never lime: charcoal `#2E2D2B`, blue `#2F55B8`, brick `#A63D2A`.

Rules: lime is never used for the user's strokes, selection, focus rings or decoration. Alarm is never decoration. Text on lime is charcoal. Contrast: charcoal on paper, panel and card passes WCAG AA; soft-ink is for 14 px notes and above only, on paper or card.

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
- Top bar 64 px, transparent: Canvases (back to home), canvas title, saved status, Focus, Ask; zoom control bottom right.
- Tool rail: left, 16 px from the edge, 60 px wide, 8 px padding, 4 px gap: pen, highlighter, eraser, lasso, shapes, text, three ink colours, undo, redo.
- Side panel (Ask, threads): right, 440 px, full height under the bar. The canvas does not resize; it pans to keep the working area visible.
- Home: 76 px header with wordmark, search and New canvas; 40 px side margins; Continue card, Recent list, All canvases grid, Archived.
- Spacing scale 4, 8, 16, 24, 40. **Every touch target is 44 px or larger** (the tablet is the primary device); 36 px chips only when they sit on the canvas next to ink.
- The canvas background is a CSS dot layer (`dot`, 1.4 px radius) that follows pan and zoom, under a transparent Excalidraw canvas. Excalidraw's own toolbar and menus are hidden.

## Elevation & Depth

Flat. Depth comes from the paper → panel → card steps, not shadows. The one shadow is for floating popovers and toasts: `0 10px 28px rgba(46, 45, 43, 0.16)`. Panels meet the canvas edge with a 1 px `pressed` rule or a rounded corner, never a shadow.

## Shapes

Rounded, never pill-shaped except the offer chip. Radii: badge 6, control 10, card 12, rail 14, panel 16 (outer corner only), offer pill 18. Dashes are for drafts only: a draft's outline is dashed lime; accepted agent text loses the dash and keeps normal ink styling.

## Components

- **Buttons.** Primary (charcoal on paper), secondary (panel), quiet (transparent, `pressed` on hover). 44 px tall, radius 10. One primary per surface.
- **Offer chip.** Lime pill, 36 px tall, 8 px charcoal dot, label such as "Answer ready" or "2 related notes". Sits beside the ink it concerns. Tapping opens a popover (card, popover shadow) with the offer and its actions ("Add links beside loss", "Not useful").
- **Draft.** Card background, dashed lime outline, lime "Draft" badge, reading text, actions Accept, Reject, Open thread. A tray at the bottom shows "N drafts on this canvas" with Jump and Accept all. Accepted and rejected states are toasts: "Added to your canvas" / "Draft removed. The answer stays in the thread." with View thread and Undo.
- **Ask panel.** Side panel: field "Your question" with the hint "To ask about one part, circle it with the lasso first", then "Earlier on this canvas" as thread rows (title, first line, time, "Draft waiting" tag).
- **Thread.** You and Agent messages, vault sources as links ("Used from your vault, opens in Obsidian"), draft actions (Show, Draw as diagram, Add to note), follow-up field with Send.
- **Focus.** A banner "Focus on. Suggestions wait until you turn it off. Ask still works." with a waiting count and Turn off. While on, offer chips are hidden.
- **Saved status.** Quiet by default: a check and "Saved". Only these states are shown: kept on this device and sending (soft-ink dot), ink only in memory (alarm dot, "do not close this tab").
- **Canvas card (home).** Card background, radius 12, 120 px thumbnail, title, "Edited 12 minutes ago, 11 chunks", optional "1 draft, 2 notes" or "Note stale" tag.

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
