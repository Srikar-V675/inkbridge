# 0088 Device journal and quiet sync status (INK-113)

## Context
`SceneSync` sent one save at a time with a 30 s timeout. A stalled PUT on the tablet held back every later stroke, and the only copy of unsent ink was memory (plus a localStorage backup on a conflict that INK-111 made impossible). Ink drawn while the network was bad was one reload away from gone, and the bar said "Saving..." for as long as it lasted.

## Decision
- A device journal in `web/src/sync/journal.ts`: IndexedDB database `inkbridge-journal`, store `entries` (key `doc NUL id NUL version`, so a put is idempotent; `{k, doc, id, version, el, acked, at}`) and store `snapshots` (key `doc`; `{doc, seq, elements, at}`). `openJournal` runs a put/get/delete probe and returns `null` (memory-only mode) when IndexedDB is missing, fails to open, or does not round-trip.
- Every changed element version is journaled 50 ms after the last change (trailing, no max wait: a stroke in progress is not worth journaling), before any request.
- `Sender` (`sync/sender.ts`) sends the unacknowledged entries (latest per id) every second as `PUT /documents/{id}/scene {base_version, elements, delta: true}` with `X-Inkbridge-Save: <tabId>:<n>`. Requests overlap; an entry already in flight is not resent; each request has an 8 s timeout; a failure backs off 1, 2, 4, 8, 15 s; the `online` event and `flushNow` ignore the backoff. The transport is the same per-element merge as `POST /elements` (decision 0080) and keeps INK-112's origin skip. It is replaced when INK-115 moves drafts off the scene.
- Opening a canvas uses the device copy if there is one: snapshot elements plus every entry merged by `winsOver`, no `GET /scene`, `loadedSeq` = the snapshot seq. After the scene is mounted App runs INK-112's `catchUp` (`GET /elements?since=`), then rewrites the snapshot with `LiveDelta.lastSeq` (the seq the server confirmed to us, never the answer to our own save) and deletes acked entries older than 7 days. With no device copy the scene is fetched and the snapshot written.
- Status: with a working journal `dirty` and `saving` show the quiet "Saved"; an entry unacknowledged for 60 s shows "Kept on this tablet, sending when the network is back" (soft-ink grey dot); a failed journal write is `error` with the red "Ink only in memory: do not close this tab". Without a journal the bar behaves as before.
- Deleted: the 409 reload path, `mergeScenes`, the localStorage backup, the `conflict` state.

## Consequences
- No localStorage backup any more. In memory-only mode there is no backup at all and the bar says so.
- The snapshot is rewritten only after an open reconcile. A session longer than 7 days without a reload may prune acked entries the snapshot lacks; the since-fetch refills them when online.
- `IdbJournal` reads all entries and filters by document; add a `doc` index if the journal grows past tens of thousands of rows.
- A journal row is written per changed version, so dragged shapes grow IndexedDB until the 7-day prune.
- A 4xx rejection drops the entries from the in-memory mirror (not resent) and leaves them unacknowledged in the journal; a reload tries them again.
- Draft-flagged elements are still journaled and PUT until INK-115 adds the sender's draft filter.
- IndexedDB on plain HTTP in Firefox for Android is unverified (owner check). If it fails, `openJournal` returns `null` and the bar shows the red line.
