# 0097: Offers in the canvas (INK-131)

## Context

INK-130 pushes `offer.created` / `offer.updated` only while the attention gate is open, and the gate reads `attention` frames (pen, view) from the browser. INK-131 is the client: chips beside chunks, popovers, Focus.

## Decisions

1. **One transformed plane for offers only.** Chips sit at scene coordinates on a `div` whose `transform` is `scale(zoom) translate(scroll)`, written straight to the style on `onScrollChange`, so a pan frame causes no React render. Each chip undoes the scale with `--z`. `ChunkOverlay` keeps its own `setView`; folding it in is deferred because bordered boxes would scale with zoom.
2. **"Open thread" deep-opens the thread** when the offer payload has `question_id` (App sets `askThread`, then opens the panel); without one it only opens the panel.
3. **Three popovers**: `related` (Jump to canvas, Open in Obsidian when `payload.vault` and `payload.file` exist, Add links beside, Not useful), `answer` (kind `answer_ready` or a `question_id` payload), and one generic (reason, Not useful). "Add links beside" posts a `write_text` op (`size: small`, anchored to the chunk) through the normal queue; the user accepts the draft as usual.
4. **`waiting` comes from the list.** `GET /documents/{id}/offers` always returns `waiting`: the number of open offers it hid because Focus is on (0 otherwise). The Focus bar shows it; turning Focus off reloads the list, because the server does not resend offers it already pushed this session.

## Attention

`{type:"attention", pen, view}` with `view` in scene units: `x = -scrollX`, `y = -scrollY`, `width = canvas width / zoom`, `height` likewise, `zoom`. A non-finite number gives `view: null`. Pen changes are sent at once; view frames at most every 500 ms (a dropped one is carried by the next frame or pen change). One view is sent on every socket open.

## Not done

Popovers are not repositioned near the screen edge. The detectors do not yet emit `vault`/`file` or answer payloads (INK-137/138).
