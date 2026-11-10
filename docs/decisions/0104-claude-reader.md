# 0104: Claude Haiku reader on the subscription (INK-185)

## Context

The Gemini free tier answers 429 for most calls, so no chunk has been read since 9 Nov. The worker also restarted its backoff at 30 s for every new chunk, so it kept hitting the limit.

## Decision

- A second reader, `recognizer/claude.py`, keeps one `claude -p` process alive (`--input-format stream-json --output-format stream-json --verbose --model haiku --tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence --setting-sources ""`, run from the temp dir). A chunk is one user line with the PNG, the answer is the next `result` event. A cold call costs about 5 s, a warm one about 1 s.
- One chunk per call through the existing `Recognizer(png, hint)` interface. No batching: the worker reads one chunk per step and the process is warm, so a JSON list adds failure modes for little gain.
- The process is killed and respawned after 25 reads, and on any error, EOF or timeout, to bound context growth.
- `INKBRIDGE_RECOGNIZER=claude|gemini` picks the reader (`make_recognizer`); Gemini stays the default, an unknown value warns and means Gemini. `INKBRIDGE_RECOGNIZE_DOCUMENTS` still decides which canvases are read; with Claude the owner may list personal ones.
- A `is_error` result mentioning "usage limit" or "rate limit" raises `RateLimited` (with `retry_after_s` from `resetsAt` when the CLI reports it); a missing binary raises the permanent `ClaudeNotFound`.
- The worker's 429 pause is now global: it doubles with each consecutive `RateLimited` across all chunks (30, 60, 120 s, ...), capped at `rate_limit_max_s` (1 h), never shorter than `retry_after_s`, and a success resets it.

## Consequences

- Readings use the subscription's 5-hour window; every read logs `claude read #n in= out= cost=` on `inkbridge.recognizer.usage`.
- The limit message is matched by substring and may need tuning against a real one. CLI flags are checked against the installed `claude --help`.
- Batching is deferred. Gemini is unchanged.
