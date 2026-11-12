# Draw, autosave, chunk, read

**Story:** as a note-taker, I want to write on the tablet and have my ink saved, grouped and readable without any manual step.

1. Open `http://<laptop>:8000/?canvas=<id>` (or pick a canvas on the home at `/`). `sync/sceneSync.ts` does `GET /documents/{id}/scene` and Excalidraw mounts before the scene arrives.
2. Draw. Ink goes to an IndexedDB device journal within 50 ms (`sync/journal.ts`) and an overlapping sender (`sync/sender.ts`) uploads changed elements with `POST /documents/{id}/elements`, idempotent by `(device, batch)`. The server merges per element (higher `version` wins, nothing deleted by omission), so there is no 409; other devices get a `scene.delta` push (decisions 0080, 0087, 0088). The status stays quiet until 61 s of failures.
3. Inside the save, the server runs the chunker (v2 by default: stroke kinds, lines, connectors, then oversized chunks cut at their widest gaps), persists chunks with stable ids, rebuilds `links`, recomputes hashes, flags `png_stale` where `stroke_hash` changed, and pushes `chunks.updated {version, stale_crops}`.
4. When the canvas is idle and saved, `sync/cropSync.ts` renders PNGs for stale chunks and uploads `PUT /regions/{id}/image` with the scene version it rendered (409 if the scene moved on).
5. If the canvas id is in `INKBRIDGE_RECOGNIZE_DOCUMENTS`, the worker waits for idle (1.5 s with the Claude reader, 5 s otherwise), reads the newest-touched chunks first with Gemini or Claude Haiku (`INKBRIDGE_RECOGNIZER`), gives the reader a box-and-arrow hint for diagrams, skips connector and `too_large` chunks, and writes `recognitions` plus the search row.
6. Agents call `read_canvas` and get chunks in reading order with text, links and the overview image.

Notes
- Moving ink changes `stroke_hash` only: crop re-rendered, no new recognition.
- Drawing never waits on recognition. Drafts are not in the scene at all.
- Save time shows in the badge and in `web/dev.log` (`timing scene.save`); `INKBRIDGE_DEVICE_LOG=1` adds a device log. Speed over weak Wi-Fi is a known limit (see roadmap).
- Files: `web/src/sync/sceneSync.ts`, `sync/journal.ts`, `sync/cropSync.ts`; `server/.../canvas/chunker/`, `api/__init__.py`, `recognizer/worker.py`.
