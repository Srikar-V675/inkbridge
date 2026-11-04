# Ask AI (pull path built; runner and panel planned)

**Story:** as a note-taker, I want to select a doubt on the canvas, ask Claude, and read the answer.

Built (INK-047, decision 0035):
1. A client posts `POST /documents/{id}/questions` (`text`, `focus_element_ids`, optional `parent_id` for a follow-up). Status `pending`; `question.update` goes out on the WebSocket.
2. Any MCP client calls `list_questions` (pending by default, oldest first). Each has `focus_chunk_ids` (computed now from live chunks) and `history` (up to 5 earlier question/answer pairs).
3. The agent reads the chunks, then calls `answer_question(question_id, answer_md, sources[])`. Sources are `{type:"chunk", id}` or `{type:"note", path}`.
4. The answer is stored as text only; no ink or vault write. A second answer, or answering a cancelled question, is 409.

```text
user/client --POST question--> API (pending) --question.update--> browsers
agent --list_questions--> API --> agent reads chunks --answer_question--> API (answered)
```

Planned:
- INK-048: optional `AgentRunner` (`INKBRIDGE_RUNNER`, Claude Code headless) that starts on a new question; failure leaves it `pending`.
- INK-049: Ask AI side panel with source chips and "Keep on canvas" (posts a `write_text` op). The web client has no panel today and ignores `question.update`.

Answer markdown is untrusted; the future panel must sanitise it.
