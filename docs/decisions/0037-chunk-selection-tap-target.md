# 0037: Chunk selection by tapping the label chip

Status: accepted (INK-065). Builds on 0024 (manual merge and split).
Code: `web/src/ChunkOverlay.tsx` (chip, highlight, `OverrideActions`), `web/src/overrides.ts`
(`toggleChunk`, `chunkMark`, `overrideUi`), `web/tests/overrides.test.ts`.

- **The chip is the tap target, not the whole box.** Each chunk's blue label chip is enlarged to at
  least 44x32 css px and is the only part of the overlay that takes pointer input. The box body keeps
  `pointer-events: none`, so drawing, panning and the rubber-band lasso (needed for Split) reach
  Excalidraw through the overlay. A whole-box target would swallow strokes drawn over ink. The
  overlay exists only while "Show chunks" is on, so with it off nothing changes for drawing.
- **Selection is Excalidraw's selection.** A tap writes the chunk's live ink ids into
  `selectedElementIds` with `updateScene({ appState })`, the same call the deep-link jump uses. No
  element changes, so nothing is saved, and there is no second selection state to keep in step.
  `planOverride` and the Merge/Split buttons then work unchanged on that selection.
- **Tap toggles.** A chunk whose live ink is all selected is removed; otherwise its ink is added to
  the current selection, so a second tap adds a second chunk for Merge. Connectors are included in
  the selection (they are part of the chunk) and ignored when a plan is decided, as before.
- **Highlight.** A chunk with all its ink (connectors ignored) selected gets a thick orange border
  and light fill; part-selected gets a dashed orange border. It shows what Merge or Split will act on.
- **The hint is visible text, not a `title` tooltip.** Tablets have no hover, so the one-line hint
  under the buttons says what a tap does and why a button is off ("already is a whole chunk").
  Buttons are at least 44 px tall.
