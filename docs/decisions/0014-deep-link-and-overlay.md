# 0014: Chunk deep link and chunk overlay

Status: accepted (INK-035). Implements F7 and tech ref 5.8 on the web side. (0012 is INK-042, 0013 is INK-032 arrow links.)

- **Lookup.** `?canvas=<id>&chunk=<chunk_id>` resolves through `GET /regions/{id}`, which already
  serves chunks with `status`, `successor_of`, `element_ids` and `bounds` (INK-031). It runs beside
  the scene load and never holds the canvas back (each request times out after 8 s); the jump is
  applied on the first change event, or on arrival if the scene is already up, without an undo entry.
  A link skips the remembered per-device view.
- **Orphans.** An orphaned chunk follows `successor_of` until an active chunk (at most 10 hops,
  cycle-safe) and shows a "Source changed" banner naming both ids. A chain that ends in an orphan
  (no successor, or a successor that is gone or on another canvas) opens at that orphan's old bounding
  box, centred and fitted (never above 100%), with a dashed ghost box until the banner is dismissed.
  Unknown ids, manual regions and chunks of another canvas show "not found"; a network failure says
  so instead of claiming the chunk is gone.
- **Highlight = selection.** The chunk's strokes that exist and are not deleted in the local scene are
  selected and `scrollToContent` fits them. Selection is app state, so nothing is written; if none of
  the ids are live locally it falls back to the bounding box.
- **Overlay is DOM, not scene.** Boxes and ids are absolutely positioned `div`s with
  `pointer-events: none`, positioned from `api.onScrollChange` (screen = (scene + scroll) * zoom).
  They are never Excalidraw elements, so autosave cannot persist them. The list is fetched when the
  toggle turns on and again after each save (chunks are re-derived on save).
- **Temporary list endpoint.** The overlay lists chunks with `GET /documents/{id}/regions?chunks=true&limit=500`
  filtered to `active` (the limit applies before that filter, so a canvas with over 500 chunk rows
  can miss some), because INK-033's `GET /documents/{id}/chunks` is not merged yet. Only
  `listChunks` in `web/src/chunks.ts` changes when it lands.
- **LAN HTTP.** Plain `fetch` and DOM only; no clipboard, `crypto.randomUUID` or other secure-context API.
