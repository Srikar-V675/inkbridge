# 0111: Reader latency

Status: accepted (INK-196). Builds on 0017 (recognition worker) and 0104 (Claude reader).

## Context

Owner test on 10 Nov: a draft or offer took 10 to 20 s to appear after writing. The worker read
candidates oldest-first from one list taken at the start of a pass, so the line just written waited
behind every unread chunk, and ink written during a read (about 3 s per chunk with the Claude
reader) waited for the whole old list. With 15 unread chunks that is about 45 s worst case.

## Changes

1. `recognition_candidates` orders by `regions.updated_at DESC` (when the user last wrote there;
   it only changes when a chunk's ink or membership changes), then id.
2. A reading is dropped when the region's content hash changed during the model call (the new
   hash gets its own read), and a pass ends early when the canvas was saved while it ran, so the
   next pass re-lists with the newest chunk first. Old backlog can be starved while the user keeps
   writing; the idle gate already defers it.
3. The idle delay defaults to 1.5 s when `INKBRIDGE_RECOGNIZER=claude` (5 s otherwise);
   `INKBRIDGE_RECOGNIZE_IDLE_S` still wins.
4. Logger `inkbridge.recognizer.latency` writes `region= latency_ms= backlog=` after each saved
   reading (stroke to reading, from the region's `updated_at`).
5. A scene save nudges the worker (`RecognitionWorker.nudge`): a daemon timer wakes the loop
   `idle_s + 0.1` s later, so a pass starts right after the idle delay instead of waiting out the
   rest of the 2 s poll.

After: one read (about 3 s) plus at most 1.5 s idle plus a short wake, instead of up to 45 s.
Not measured on a real canvas here; the tests use an injected clock.

## Left out

- Merging same-row fragments (ticket item 5): chunker work, owned by INK-195.
- The 3 s offer quiet window (`INKBRIDGE_QUIET_S`) is untouched.
- A crop must still be fresh (the browser uploads it when idle), so the nudge only helps once the
  crop is there; server crop mode renders it itself.

## Owner check

Write a short line on the tablet with a backlog of unread chunks and confirm the draft or offer
appears within about 5 s of lifting the pen (grep `inkbridge.recognizer.latency` in the API log).
Judge whether the quiet window still feels slow.
