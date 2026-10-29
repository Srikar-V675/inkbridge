# 0020: check_sync statuses, successors and the bounded wait

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
  - Active with an equal content hash: `fresh` (a moved chunk keeps its content hash, so it costs
    nothing). The exception is a current reading the note does not have. That happens when the
    note was exported before recognition ran, or when a user or agent corrected the reading of
    the same ink. Then the chunk is `changed` with that reading; otherwise the new text would never
    reach the note. This is stricter than the spec's "fresh = content hash equal", in the spirit of
    early cutoff: the reading changed. A reading that vanished (null now) stays `fresh`.
  - Otherwise the best current reading (user > agent > gemini) decides. If its `text_hash` equals
    the note's reading, the result is `fresh_after_reread {id, hash, reading}`, so the skill only
    updates the stored hash. If not, it is `changed {id, hash, reading}`.
  - A missing reading never matches, even when the note's reading is also null. That chunk is
    `changed` with `reading: null`, which errs towards a visible update and is never a silent miss.
- **New.** `new` lists the canvas's active chunks that the note does not list and that no
  `replaced` entry names as its successor. A merged chunk would otherwise appear twice, once as the
  successor and once as new. Entries come in reading order, each with `{id, hash, reading,
  preview}`, where `preview` is the first 80 characters of the reading or null.
- **Bounded wait.** Some listed (or successor) chunks may have changed ink, no reading yet, and a
  fresh crop. The API hands their ids to the recognition worker with
  `RecognitionWorker.request()`. That wakes the thread and lets those ids skip the idle delay, but
  only those ids and only for `wait_s`.
  - `request()` returns the ids it will actually try. It returns none when the canvas is not opted
    in (privacy gate), the worker is stopped or not running, or calls are paused after a 429. It
    leaves out any id still in its backoff.
  - The API waits only for the ids it got back. It polls every 0.2 s with an async sleep, so no
    threadpool thread is held, until the readings exist or `wait_s` passes.
  - A stale crop cannot be read until the browser re-exports it, so it is not waited for. That
    chunk, like a recognizer timeout or a slow model, ends as `changed` with `reading: null`.
  - The final classification runs on one read snapshot (`BEGIN` ... rollback), so a save landing
    mid-check cannot mix two scenes.
- **Duplicates and merges.** A repeated id is reported once: the first occurrence wins and later
  entries are ignored. After a merge, several `replaced` entries can name the same successor. The
  export skill rewrites that successor's block once.
- **Pure read.** check_sync never writes the scene, a region, a document or a note. The only write
  it can cause is the worker's recognition row, written in the worker's own thread.
- **MCP.** The `check_sync` tool posts the same body and gives the HTTP call `wait_s + 30` s.
