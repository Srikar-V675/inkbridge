# 0019: write_text returns at once; a new canvas shows its first drafts

Status: accepted (INK-043)

- **`write_text` does not wait for a browser.** Unlike `draw_diagram`, nothing needs converting:
  the op holds the text and its server-computed placement, and any browser draws it as a draft
  now or when the canvas is next opened (pending and delivered ops are replayed, decision 0012).
  The tool returns `{op_id, status: "pending", placement}` at once, so an agent can write into a
  canvas that nobody has open, for example one it just made with `create_canvas`.
- **Stacking.** Several writes without an anchor stack downward without overlapping. Each op
  reserves its estimated box while it is pending, delivered or applied (decision 0009).
  The tests check this across mixed anchored and free writes, on the default canvas and on a new
  one. In the browser run, the real text boxes measured after layout did not overlap either.
- **`create_canvas` only adds.** It calls `POST /documents`, which always makes a new id. The
  tool takes only a title, so it has no way to name or change an existing canvas.
- **A new canvas shows its first drafts.** A canvas opened empty with no remembered view used to
  leave drafts at the origin, under the toolbar. The web app now fits the view to the first
  drafts that arrive on such a canvas, once. It stops as soon as the user draws, pans or zooms
  (`keepFittingFirstDrafts` in `web/src/view.ts`), so drafts never move a view the user is
  working in.
- **Caps on what an agent can pile up.** The LAN API has no auth, so an agent caught in a loop
  could otherwise grow the database without limit:
  - at most 500 canvases in all (`409 too_many_canvases`);
  - at most 200 ops per canvas still waiting for a browser, pending or delivered
    (`409 too_many_open_ops`). Drawn, resolved and expired ops do not count.

  Both error messages say what to do instead.
- **Anchor errors name the fix.** `anchor_not_found` carries a `msg` pointing to `read_canvas`.
