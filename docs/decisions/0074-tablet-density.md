# 0074: Tablet density

Status: accepted (INK-170). Owner check pending: on the tablet (landscape, with browser chrome) the whole rail is visible or scrolls, including Undo and Redo; the zoom pill is easy to hit but no longer dominant; dots feel fine and quiet while drawing, panning and pinch-zooming, with no stutter.

## Context

Owner issues of 6 Nov: on the tablet in landscape with browser chrome (visible height 600 to 700 px) the tool rail was cut off and Redo was lost. The rail is 572 px tall (11 buttons of 44 px, two spacers, gaps and padding) and had no height cap, so it overflowed whenever the visible height was under about 676 px. The zoom control (148 x 44 px pill) felt large next to the ink. Dots at 24 scene units with a 1.4 px radius read heavy on the paper.

## Decision

- **The rail is capped to the viewport.** `max-height: calc(100dvh - var(--ink-rail-top) - var(--space-md))` with a `100vh` fallback, `overflow-y: auto`, and it scrolls when still too tall. `dvh` follows the address bar and orientation changes with no JS, so no listener is added. Under 720 px of height the rail packs (gaps 0, section gap 6 px, top 72 px); 11 x 44 + 2 x 6 + 8 = 504 px fits 600 px of visible height. Touch targets stay 44 px.
- **The zoom pill is 36 px tall visually.** Its buttons are 32 px with a `::after` pseudo-element at `inset: -6px`, which gives a 44 px hit area. The value is not a button.
- **Dots are finer and lighter.** `TILE` goes from 24 to 36 scene units (still doubled while a gap is under 10 px). The radius goes from 1.4 to 1 px. The colour is a new `paper-dot` token (`#D9D1C0`) rather than a recoloured `dot`, because Home card borders use `dot`.
- **Tablet top bar.** Under 1300 px or on a coarse pointer, the title is 18 px and the status 13 px, the bar gap is 8 px, and the rail sits 8 px from the edge. The bar height stays 64 px, so the Ask panel and overlays that offset by it do not move.
- **No JS and no server change.** Everything is CSS or a constant, so the work does not touch the op queue, the scene, or any invariant.

This supersedes the 24-unit tile in [0066](0066-app-shell.md) and the Main board's dot spacing; 0066's other decisions stand.

## Consequences

- INK-174 may repaint the dots. It must keep `TILE`, the `dotStep` thinning and the centre-of-tile alignment test (`shell.test.ts`).
- INK-175 adds a rail flyout. It must keep the rail inside its `max-height` (scroll, not overflow).
- The 1300 px breakpoint also matches a 1280 px laptop window; that window gets the denser top bar by design.
- Tablet numbers are measured in headless Chromium only. The tablet check is an owner check.
