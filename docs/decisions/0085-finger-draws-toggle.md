# 0085 Finger draws toggle: pressed look and penMode reconcile (INK-180)

Status: accepted, tablet check pending (press on: button charcoal and a finger draws; press off: button quiet, one finger pans, two pinch; with a stylus touch in between and after a reload; confirm the button looks off right after the second tap).

## Report
The owner saw "Finger draws" stay on after a second press and the button never go back to inactive (7 Nov, tablet).

## Repro (before any fix)
`web/scripts/touch/finger-cycle.mjs` drives the real app in Chromium (touch enabled) with synthetic touch and pen pointer events on `canvas.interactive`, on a throwaway canvas. Each touch drag is classified `drew` (one element added, view unchanged) or `panned` (view moved, no element). Unmodified code:

| step | observed |
|---|---|
| A fresh: aria-pressed false, touch drag | panned |
| B click on: aria-pressed true, touch drag | drew |
| C pen stroke, then touch drag | drew |
| D click off (mouse left over the button): aria-pressed false, touch drag | panned |
| D computed background, on vs off with hover | `rgb(222, 214, 198)` vs `rgb(222, 214, 198)` (same) |
| E pen stroke with it off, then touch drag | panned |
| F reload off, on (after a pen stroke), off | state restored each time, `panned` / `drew` / `panned` |
| G the same cycle with touch taps on the button | all behaviour steps pass |

Every behavioural step passed. Only the look failed.

## Root cause
The button reused the shared `ink-chunk-toggle` class, whose only rule is `[aria-pressed="true"] { background: var(--color-pressed) }` (#DED6C6). The quiet button's hover colour is `--color-pressed` too, so pressed and hovered look identical. On a touch screen `:hover` sticks to the last tapped element, so after the second tap the button kept the pressed colour while the state was off: it looked as if it never turned off. On, the faint beige on paper was also easy to miss.

## Ruled out, by the repro and by reading Excalidraw 0.18.1 (`dist/dev/index.js`)
- (a) `penPatch` / pen detection: the first pen contact (`:27431`) sets `penMode` and `penDetected` only when `penDetected` is false; `penPatch(true)` sets it, `penPatch(false)` leaves `penMode: true`, so the flip is harmless in both states. The touch gate is `:27512`. Step C and E pass.
- (c) two store instances: `fingerDrawsStore.ts` is the only `createFingerDraws`; FastInk, the router and the button share it (a unit test documents that a second instance would disagree).
- (d) value read once: the router gets `fingerDraws.get`, a live read per pointerdown.

## Fix
- The toggle has its own class `ink-finger-toggle` with `TouchLayer.css`: on is a charcoal fill with paper text (like a pressed rail button) that also wins over the quiet hover; under `@media (hover: none)` off resets the hover tint, so a tablet's stuck hover cannot look like on. Tokens only; `DESIGN.md` Touch bullet gets one sentence.
- `reconcilePen(appState, fingerDraws)` (pure, `touchRouting.ts`): `null` when `penMode` already equals `!fingerDraws`, otherwise `penPatch`. `TouchRouting` applies it after load, on every toggle and on every Excalidraw `onChange`, so the store stays the only truth even if Excalidraw writes `penMode` itself. It compares only `penMode`, so the legitimate `penDetected` flip on the first pen contact while off writes nothing, and the guard keeps it from looping.

After the fix the same script passes every step, the on colour is `rgb(46, 45, 43)` against transparent for off (hover or not, also after a touch tap).

## Notes
- Headless Chromium with `hasTouch` reports `hover: none`, so the script exercises the touch-screen rule. The real tablet is the actual test.
- Known limit, unchanged from 0072: a stylus that reports `pointerType: "touch"` cannot be told from a finger.
- Follow-up, not done: the Chunks toggle uses the same shared class and has the same sticky-hover look.
- On, the toggle has the same charcoal fill as the Ask button; the lime rule is not involved (charcoal is not lime).
