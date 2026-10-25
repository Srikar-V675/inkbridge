# 0012: Crop sync for chunks (browser renders, server checks the scene version)

Status: accepted (INK-057). Implements tech ref 9.4.

- **Who renders.** Only the browser renders Excalidraw faithfully, so `web/src/cropSync.ts` exports
  each stale chunk's live elements with `exportToBlob` (white background, 10 px padding, longest
  side at most 2048 px) and uploads it with `PUT /regions/{id}/image`.
- **Which chunks.** INK-033's `GET /documents/{id}/chunks?png_stale=1` is not merged yet, so the
  client lists `GET /documents/{id}/regions?chunks=true&png_stale=true&limit=500` (a new
  `png_stale` filter on the existing list) and skips orphaned chunks. Switching to the chunks API is
  one URL in `cropSync.ts`.
- **When.** Never while drawing: no pass starts, and a running pass stops, while a pointer is down
  on the page or within 2 s of the last scene change or pointer event; a crop exported while an edit
  happened is discarded, not uploaded. A pass runs only when the canvas equals a stored scene
  (`SceneSync.settledVersion()`: loaded, nothing pending, no save in flight). Triggers: the first
  canvas change event after load (a reopened tab catches up), every `saved` state, and a 30 s poll
  until INK-042's WebSocket can call `request()` on `chunks.updated`.
- **Ink version check** (closes the INK-031 review minor: the upload cleared `png_stale` without
  knowing which ink the crop showed). The upload sends `scene_version`, the scene the canvas held when
  it rendered. If the stored scene is at another version the API answers 409 `{current_version}` and
  writes nothing. Clearing the flag is one compare-and-set statement against the scene version, so a
  save landing between the file write and the clear leaves `png_stale=1` (also 409). The scene
  version is coarser than the chunk's `stroke_hash` (an edit elsewhere also rejects the crop), but it
  is the only thing that proves the browser's elements are the stored ones; the next idle pass
  simply exports again. `scene_version` stays optional, so callers that do not send it keep the old
  behaviour.
- **Temp files.** Each upload writes its own `<crop>.<random>.tmp` before the atomic rename, so two
  tabs uploading the same crop never interleave bytes in a shared temp file.
- **Multiple tabs.** A tab whose scene is behind (another tab saved) gets 409 and leaves the work to
  the tab that saved; it does not loop (a 409 ends the pass until the next save or poll).
