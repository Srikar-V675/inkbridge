# 0035: Questions API and the pull path (INK-047)

Status: accepted, 2 Nov 2026.

Scope: store questions, list them, store answers, over REST and MCP. INK-046 (the runner spike) was
waived, so there is no `AgentRunner` and no `INKBRIDGE_RUNNER`; that is INK-048. 0007 stays reserved
for the INK-046 spike and is not written here. A runner failure cannot strand a question because
nothing but answer or cancel ever moves a row off `pending` (tested).

1. `focus_element_ids` are stored as sent (unknown ids accepted). `focus_chunk_ids` are computed
   at read time from active chunks that share an element, because chunk ids change on split and merge.
2. History is the ancestors through `parent_id`, oldest first, at most 5, as `{id, text, answer_md,
   status}`. It is built from rows only, so it survives a restart and needs no session state.
3. Transitions: `pending -> answered` and `pending -> cancelled`; anything else is 409
   `invalid_transition`. The guard is in the `UPDATE ... WHERE status = 'pending'`, so racing
   answers cannot both win. A follow-up's parent must be a question on the same canvas (422
   `parent_not_found`), in any status.
4. Sources are `{type:"chunk", id}` or `{type:"note", path}`, no other keys, max 50; chunk ids are
   format-checked, not existence-checked (chunks can disappear). Limits: answer 20,000 chars,
   question 4,000, focus 200 ids.
5. `list_questions` defaults to `pending`, oldest first (FIFO for an answering agent), limit 1..100.
6. The backend stores answer text only: no vault write, no ink edit. The markdown is untrusted;
   whatever renders it (INK-048 panel) must sanitise it.

Each create, answer and cancel publishes `{"type": "question.update", "question": {...}}` on the
canvas WebSocket; the web client ignores unknown message types.
