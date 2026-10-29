# Draw, autosave, chunk, read

**Story:** as a note-taker, I want to write on the tablet and have my ink saved, grouped and readable without any manual step.

1. Open `http://<laptop>:5173/?canvas=<id>`. `sceneSync.ts` does `GET /documents/{id}/scene`.
2. Draw. Autosave sends `PUT /documents/{id}/scene` with `base_version`. A 409 triggers a merge of the server scene into the local one and a retry (decision 0008).
3. Inside the save, the server runs the chunker, persists chunks with stable ids, rebuilds arrow `links`, recomputes hashes, flags `png_stale` where `stroke_hash` changed, and pushes `chunks.updated {version, stale_crops}`.
4. When the canvas is idle and saved, `cropSync.ts` renders PNGs for stale chunks and uploads `PUT /regions/{id}/image` with the scene version it rendered (409 if the scene moved on).
5. If the canvas id is in `INKBRIDGE_RECOGNIZE_DOCUMENTS`, the worker waits for idle, reads chunks with a fresh crop and no reading for their `content_hash`, and writes `recognitions` plus the search row.
6. Agents call `read_canvas` and get chunks in reading order with text, links and the overview image.

Notes
- Moving ink changes `stroke_hash` only: crop re-rendered, no new recognition.
- Drawing never waits on recognition. Drafts are skipped by the chunker.
- Files: `web/src/sceneSync.ts`, `cropSync.ts`; `server/.../chunker.py`, `api/__init__.py`, `recognition_worker.py`.
