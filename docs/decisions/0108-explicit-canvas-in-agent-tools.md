# 0108: Wrong-canvas errors name the canvas; agent tools echo it (INK-191)

## Context

Three agent errors were all one mistake: the agent worked on canvas B but the MCP client fell back to `INKBRIDGE_DOCUMENT` (default `default`) because `document_id` was omitted. The result was `chunk_not_found` (draw_diagram `from_chunks`), `question_not_found` (op `question_id`), `task_other_canvas` (op budget), and a bare "question not found" from `answer_question`/`get_question`, which address a question by id only. The runner prompts named the canvas but never told the agent to pass it.

## Decision

- Server errors name the requested canvas and where the object actually is: `chunk_not_found` carries `document_id`, `found_on` (null when no canvas has the chunk) and a `msg` pointing at `read_canvas`; `anchor_not_found` and `question_not_found` name the canvas; `task_other_canvas` names the task and both canvases; question 404s carry the question id.
- `POST /questions/{id}/answer` takes an optional `document_id`; a mismatch is refused with 409 `question_other_canvas` naming both canvases (also for `final: false`). Omitted means no check (back compat).
- MCP `answer_question` takes `document_id?`; `answer_question`, `list_questions`, `write_text`, `draw_diagram` and `edit_diagram` echo `document_id` in their result, so an agent sees which canvas it hit.
- Runner prompts (question and task) tell the agent to pass `document_id="<canvas>"` on every tool call.
- The `INKBRIDGE_DOCUMENT` fallback stays, so single-canvas MCP setups keep working.

## Consequences

- A stale chunk id after re-chunking still reports `found_on: null`; it is not distinguished from a typo.
- Enforcement for `answer_question` is server-side only when the agent passes `document_id`; the prompt makes that likely, not certain. INK-188 may later make the canvas required.
- `list_questions` is still `{questions}` plus a sibling `document_id`; no known consumer reads a strict shape.
