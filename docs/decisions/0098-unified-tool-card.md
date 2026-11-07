# 0098: One card per tool

Status: accepted (INK-178). Owner check pending: tablet (see Consequences). Supersedes the flyout part of [0075](0075-properties-panel.md).

## Context

0075 gave the app two controls: a Shapes flyout (five shape buttons) and a properties card. Pen, highlighter and eraser had none: the pen's width, colour beyond the three rail swatches and opacity could not be changed.

## Decision

- **One control.** `PropsCard` is the only one. The shapes picker is a first row inside the Shapes card (`role="toolbar"`, five 44 px buttons, `aria-pressed` from `railStore.shape`; picking keeps the card open and the rows update in place). `ShapesFlyout`, its fixed-position wrapper and its z-index 7 case are removed.
- **Which tools have a card.** `sourceFor` now treats freedraw as a tool source. Eraser, hand, laser and select with no selection have none. A non-empty selection still wins and ignores the open state (the selection card is unchanged).
- **Open rules.** Shapes and Text open by default, Pen and Highlighter closed (`OPEN_DEFAULT`), so the card never appears over handwriting by itself. Tapping the already-active rail button calls `toggleCard()`; tapping an inactive one is `tap()` as before. Open state is remembered per card tool (`pen`, `highlighter`, `shapes`, `text`) in `propsStore`, session only.
- **Pen versus highlighter.** Opacity used to tell them apart (below 100 is a highlighter); the pen card edits opacity, so a pen at 50 percent would read as a highlighter. `railStore` remembers the kind of the last pen or highlighter tap (and the pen it picks at start) and passes it to `railTool`; the props store reads it through `env.freedrawKind()`. Without a remembered kind the opacity rule still applies.
- **Colour sync.** The pen card's stroke writes `currentItemStrokeColor`, the field the rail turns into its swatch index, so no extra state. Pen and highlighter show the first four palette entries (three inks and soft-ink); shapes and text keep all five.
- **Writes.** Pen, highlighter and shape card edits are tool defaults written with `CaptureUpdateAction.NEVER`. No path emits `points`, `pressures` or `simulatePressure`; the freedraw safety tests stay.

## Consequences

- A pen at 50 percent stays a pen on the rail. After a tool switch via undo or a deep link the kind falls back to the opacity rule until the first tap.
- Tapping the active pen no longer re-runs `tap("pen")`, so the reset of opacity and width happens only when switching tools.
- Owner checks on the tablet: the pen and highlighter card never opens by itself and a tap on the active button opens and closes it; the card does not cover the page while writing; the shapes picker row and the properties are easy to hit; a recoloured pen stroke after a highlighter or shape session looks right.
