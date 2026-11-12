# Ask AI (panel, pull path and runner built)

**Story:** as a note-taker, I want to select a doubt on the canvas, ask Claude, and read the answer beside my ink.

1. The Ask panel (`web/src/ask/`) posts `POST /documents/{id}/questions` (`text`, `focus_element_ids`, optional `parent_id` for a follow-up; a follow-up with no selection inherits its parent's focus, decision 0061). Status `pending`; the server also creates an `agent_tasks` row and publishes `question.update` on the WebSocket. The panel shows threads derived from `parent_id` (decision 0096).
2. Push path (optional): with `INKBRIDGE_RUNNER=claude`, `agent/ask_runner.py` starts `claude -p` for the task. The prompt carries `CANVAS_CONTEXT` (the agent is told it is inside a handwritten canvas, decision 0122), the canvas id (decision 0108) and the tools allowed for the task's mode (`question`, `revise`, `brief`, `markup`). It accepts read-only vault tools by name (decision 0060). Three failed attempts show `runner_status` / `runner_error` in the panel. A daily cap (`INKBRIDGE_AGENT_DAILY_TASKS`, 30) applies to tasks the user did not ask for; questions are exempt.
3. Pull path: any MCP client calls `list_questions` (pending first, oldest first) with `focus_chunk_ids` and `history`, or `list_tasks` / `claim_task` / `complete_task`.
4. The agent reads the chunks (`read_canvas`, `get_region`, `retrieve`), then calls `answer_question(question_id, answer_md, sources[])`. Sources are `{type:"chunk", id}` or `{type:"note", path}`. With `final=false` it streams: `partial_answer` is stored and the browser receives `question.delta` (decision 0099).
5. The panel renders the answer as safe markdown with source chips that jump to the chunks, "Keep on canvas" (a `write_text` draft), and "Draw as diagram". The answer can also be drawn in place as a draft under its anchor (decision 0116). Answers are stored as text only; a second answer, or answering a cancelled question, is 409.

```text
panel --POST question--> API (pending, task) --question.update--> browsers
runner or MCP client --claim task / list_questions--> read chunks --answer_question (stream)--> API
API --question.delta / question.update--> panel
```

Answer markdown is untrusted; the panel sanitises it (`ask/askMarkdown.ts`). Decisions 0007, 0035, 0046, 0060, 0061, 0095, 0096, 0099, 0122.
