# Ask AI (planned, INK-046..049)

**Story:** as a note-taker, I want to select a doubt on the canvas, press Ask AI, and read the answer in a side panel.

Design (tickets, not code):
1. The panel posts `POST /documents/{id}/questions` (text, `focus_element_ids`, optional `parent_id`). The question is `pending`.
2. Pull path (vendor neutral): any MCP client calls `list_questions` (with focus chunk ids and history from the `parent_id` chain) and `answer_question(question_id, answer_md, sources[])`.
3. Push path (optional): `INKBRIDGE_RUNNER` selects an `AgentRunner` adapter (Claude Code headless for the demo); one question at a time per canvas, with a timeout; failure leaves the question `pending`.
4. The browser receives `question.update` over WebSocket and shows the answer with source chips (chunk chips pan to the chunk).
5. "Keep on canvas" posts a `write_text` op, so the answer arrives as a draft.

Never depends on one vendor's session resume. Only the `questions` table exists today. Cut-list: keep the pull path.
