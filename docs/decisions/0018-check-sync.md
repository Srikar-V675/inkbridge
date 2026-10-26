# 0018: check_sync statuses, successors and the bounded wait

Status: accepted (INK-036). Implements tech ref 8.4 and 9.7.

- **Input.** `POST /documents/{id}/check_sync` with `{chunks: [{id, hash, reading}], wait_s}`, where
  `hash` is the chunk's content hash and `reading` its reading hash (`text_hash`) as stored in the
  note. Up to 2000 chunks; `wait_s` 0..30, default 15. An unknown canvas is 404. A repeated id is
  reported once (first occurrence wins).
- **Classification**, in order:
  - The id is unknown or belongs to another canvas: `removed` (never an error).
  - Orphaned: follow `successor_of` to the first active chunk. That gives `replaced {id, successor,
    hash, reading}` with the successor's hashes. A dead end, a cycle or more than 64 hops gives
    `removed`.
  - Active with an equal content hash: `fresh`. A moved chunk keeps its content hash, so it costs
    nothing.
  - Otherwise the best current reading (user > agent > gemini) decides. If its `text_hash` equals
    the note's reading, the result is `fresh_after_reread {id, hash, reading}`, so the skill only
    updates the stored hash. If not, it is `changed {id, hash, reading}`.
  - A missing reading never matches, even when the note's reading is also null. That chunk is
    `changed` with `reading: null`, which errs towards a visible update and is never a silent miss.
- **New.** `new` lists the canvas's active chunks that the note does not list and that no
  `replaced` entry names as its successor. A merged chunk would otherwise appear twice, once as the
  successor and once as new. Entries come in reading order, each with `{id, hash, reading,
  preview}`, where `preview` is the first 80 characters of the reading or null.
- **Bounded wait.** Some listed (or successor) chunks may have changed ink but no reading yet. The
  API hands their ids to the recognition worker with `RecognitionWorker.request()`. That wakes the
  thread and lets those ids skip the idle delay, but only those ids and only for `wait_s`.
  Everything else still applies: the canvas opt-in (privacy gate), a fresh crop, backoff and the
  global 429 pause. The API then polls the database every 0.2 s until the readings exist or
  `wait_s` passes. If there is no worker, or the canvas is not opted in, `request()` returns false
  and the API answers at once. A recognizer timeout, a slow model or a stale crop all end as
  `changed` with `reading: null` at the deadline.
- **Pure read.** check_sync never writes the scene, a region, a document or a note. The only write
  it can cause is the worker's recognition row, written in the worker's own thread.
- **MCP.** The `check_sync` tool posts the same body and gives the HTTP call `wait_s + 30` s.
