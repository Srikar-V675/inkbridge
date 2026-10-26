# 0017: Recognition worker, opt-in canvases, cache and backoff

Status: accepted (INK-014). Implements tech ref 6 and 9.5.

- **Opt-in per canvas (privacy).** The Gemini free tier may train on what it receives, so the worker
  starts only when `INKBRIDGE_RECOGNIZE_DOCUMENTS` lists canvas ids (comma-separated, no wildcard),
  and only those canvases' crops are ever sent. Unset or empty means no worker and no model calls. A
  missing or rejected key logs a warning and the API starts without the worker.
- **What is read.** Active regions (chunks and manual regions) with `png_stale = 0`, a crop file on
  disk, and no `recognitions` row of any source for their current `content_hash`. A moved chunk keeps
  its content hash and so its reading: zero calls. An edited chunk has a new hash: one call. A
  user or agent reading for the hash also means no call. A stale crop is never read, even when an
  old file exists, because it shows the ink before the edit; the browser's crop sync (INK-057)
  refreshes it and the next pass reads it.
- **Never blocks drawing.** One daemon thread with its own SQLite connection polls every 2 s. A
  canvas is read only after it has been idle for `INKBRIDGE_RECOGNIZE_IDLE_S` (default 5 s, from
  `documents.updated_at`), re-checked before every call. No transaction is open during a model call;
  the save is one short write (`save_recognition`) that commits at once.
- **Rate limit and failures.** Calls are sequential in that one thread; `GeminiRecognizer` already
  spaces them 4 s apart and retries 429 (decision 0006). Any other failure (429 after its retries,
  timeout, bad reply, unexpected exception) backs off for that (region, content hash): 30 s, doubling,
  capped at 10 min. It is logged to stderr and never reaches the editor. A `PermanentError` (missing
  or invalid key) stops the worker and logs once. Backoff state is in memory, so a restart retries.
- **What is stored.** `source = 'gemini'`, model, text, latex, `text_hash`, keyed by the content hash
  the crop was read for (still correct if the ink changed during the call: that hash keeps its
  reading). The FTS row is rebuilt from the best reading (user > agent > gemini). An auto chunk whose
  ink still has that hash takes the model's `kind`; a manual region keeps its creator's kind.
- **Push.** After a pass that saved readings the worker publishes `chunks.updated {version,
  stale_crops, recognized: [ids]}` through the WebSocket hub (INK-042), so an open tab can refresh.
  The worker module never imports `inkbridge.api`; the API hands it `hub.publish`.
