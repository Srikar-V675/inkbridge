# 0083: UI size for the shell

Status: accepted (INK-177). Owner check pending: pick the default size on the tablet (the proposal is Small, 0.8, on a coarse pointer); confirm every control is still easy to hit at Small; confirm the owner meant UI size, not canvas zoom.

## Context

Owner issue of 7 Nov: the shell chrome (tool rail, top bar, zoom pill, properties card, Ask panel, drafts, chunk tabs) is too big on the tablet and takes room from the canvas. Decision [0074](0074-tablet-density.md) shrank some type and the zoom pill but left every control at 44 px. The owner wants about 20 percent smaller overall, kept as a setting, without losing touch reliability.

## Decision

- **One scale, set on the shell.** `Shell.tsx` sets `--ui-scale` inline on `.ink-shell` from a small store (`web/src/app/uiScale.ts`, `uiScaleStore.ts`; the `fingerDraws` pattern). Presets: Small 0.8, Medium 0.9, Large 1.0. The default is Small on a coarse pointer and Large on a fine one; the choice is remembered per device (`inkbridge-ui-scale`). `?ui=0.7` applies and remembers a custom value between 0.6 and 1.2 (like `?devicelog`), `?ui=0` forgets it. The top bar has a quiet "Size S/M/L" button left of "Finger draws" that cycles the presets.
- **Mechanism: a scoped token override.** `web/src/app/uiScale.css` redeclares the `--space-*`, five `--type-*-size` and the `--component-*` size tokens on `.ink-shell` as `calc(<value> * var(--ui-scale, 1))`. Everything inside the shell reads tokens, so no component changed, `tokens.css` and `DESIGN.md` front matter are untouched (their values are "Large"), and Home and the Kit, which sit outside `.ink-shell`, stay unscaled. A test compares every line of the block with `tokens.css`, so a changed token fails it until the block follows. Hard-coded sizes that tokens cannot reach (rail top, zoom pill, props card width, Ask paddings, draft card width, chunk dock and actions) were turned into the same calc.
- **Not CSS `zoom` or `transform: scale`.** Either would shrink the hit areas along with the faces, and `getBoundingClientRect` (used for the shapes flyout and the chunk tabs) would no longer match layout. Changing layout sizes keeps both honest.
- **The hit area is never scaled.** `--space-touch` (44 px) is not overridden. `.ink-icon-button` and `.ink-button` get a `::after` box at `inset: min(0px, calc((var(--ui-scale, 1) - 1) * var(--space-touch) / 2))` (vertical only for `.ink-button`), which is 44 px at every scale up to 1 and nothing above; the zoom pill uses the same idea. Neighbouring hit areas overlap by up to about 6 px at Small and about 9 px in a packed rail, and the later sibling wins in the overlap (a tap near the edge of two buttons goes to the lower or right one). Icons and colour dots shrink with the face by `scale`.
- **Type floor of 12 px.** Type tokens are `max(12px, ...)`, so notes stay legible at 0.7 to 0.8. The soft-ink "14 px and above" contrast note in `DESIGN.md` now says 12 px at Small. The Ask follow-up field stays at 16 px so a text field does not trigger focus zoom on the tablet browser.
- **Not scaled on purpose:** radii, the 36 px chip (it sits beside ink and is the one sub-44 target), the 44 px chunk tab hit box, the 28 px slider thumb, and 1 to 3 px borders and outlines. Ask text sizes that were literal px now read the type tokens so they scale with the rest.

## Consequences

- New components in the shell must read tokens: a hard-coded px inside `.ink-shell` will not scale.
- INK-178 (card and rail) must keep the `uiScale.css` drift test green and use `--space-touch` only for hit areas.
- Headless Chromium measured the shell at 1180 x 820 and 1024 x 768 for scales 1, 0.9, 0.8 and 0.7: rail 60, 54, 48 and 42 px wide, top bar 64, 57.6, 51.2 and 44.8 px, zoom pill 36, 32.4, 28.8 and 25.2 px; the canvas stays the full viewport, canvas zoom does not change, and the flyout, props card and chunk tabs keep their anchors. All eleven tools fit at 1024 x 768 and 0.8 without scrolling. The tablet itself is an owner check.
- `calc()` inside `max()` and `min()` custom properties and the `scale` property need Safari 14.1 or Chromium 104 or later; an older browser falls back to unscaled sizes, which still work.
