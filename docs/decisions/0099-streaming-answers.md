# 0099 Stream the agent's answer into the Ask panel (INK-176)

## Decision

- Migration 0018 adds `questions.partial_answer TEXT` (NULL = not streaming) and
  `partial_seq INTEGER NOT NULL DEFAULT 0`. They live on the row, not in a side table: one writer,
  read together with the question.
- `partial_answer` is cumulative text and every append bumps `partial_seq` by 1, capped at 20,000
  chars (422 `partial_too_long`). The final `answer_question` sets `partial_answer = NULL` and keeps
  `partial_seq`, so the final answer replaces the partial. A runner retry or failure calls
  `reset_partial` (NULL, 0) and publishes a `question.update`, which replaces the client's question.
- WebSocket `question.delta {id, seq, text}` carries the appended piece. Client rule:
  `seq == partial_seq + 1` appends; `seq <= partial_seq` is a duplicate and ignored; anything else
  (a gap, an unknown or non-pending question) refetches. `question.update` always overwrites.
- Pull path: `answer_question(..., final=true)`. With `final=false`, `answer_md` is a chunk appended
  to the partial (sources and canvas_text ignored), the question stays pending and the tool returns
  `{id, status:"pending", seq}`. A client that never sets `final` behaves exactly as before.
- Runner path: the child writes the answer inside the arguments of its `answer_question` tool call,
  so text deltas would be its reasoning, not the answer. The runner runs `claude -p` with
  `--output-format stream-json --verbose --include-partial-messages`, follows the
  `input_json_delta` pieces of the `answer_question` tool_use block and extracts the growing
  `answer_md` string from the partial JSON (`agent/answer_stream.py`).
- The sink writes through the worker's own connection and thread (the runner reads stdout in the
  worker thread), so there is no second writer. Appends are throttled to one per 150 ms; the tail
  held back by the throttle is covered by the final answer. A sink error is logged (class only) and
  the child is still read to the end.
- `ClaudeCodeRunner.run` now reads stdout in a loop with a `threading.Timer` for the timeout, and
  writes the prompt in a thread so a prompt over the 64 KB pipe cannot deadlock.
- Panel: the partial renders through `AnswerMarkdown` (skipHtml, safe hrefs). react-markdown closes
  an unclosed fence at end of input and drops raw html, so no fence-fixing helper exists; a test pins
  that. "Writing..." replaces the runner line, Cancel stays, follow-up Send is disabled while the
  last message streams.

## Assumptions to check on the tablet

The stream-json event shape and the three `claude` flags come from the documented format and a fake
stream, not a live run. If the installed `claude` emits no `input_json_delta` for the tool call, the
panel shows no partial and the final answer still lands.
