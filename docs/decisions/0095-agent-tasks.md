# 0095 Agent tasks: one queue, modes, two paths (INK-133)

## Context
Questions and tapped offers need one queue that both the Ask runner and any MCP client can work, with limits on what a task may draw.

## Decision
- Table `agent_tasks` (migration 0016) as in tech ref v4, plus `claimed_at` (needed for the daily cap). A task has a `kind` (what created it: `question`, `offer`, `revise`, `brief`) and a mode (what it may do) in `input_json["mode"]`: `question` (write_text, draw_diagram, 3 drafts), `diagram` (draw_diagram, 2), `link` and `brief` (no drafts).
- Offer kind to mode: `sketch` -> `diagram`; `dangling_arrow`, `related` -> `link`; anything else -> `question`. `revise` -> `diagram`, `brief` -> `brief`.
- A question task is created in the same transaction as the question and finished when the question is answered (`done`) or cancelled (`cancelled`). Pending questions are backfilled by the migration. A tapped offer creates its task in the tap transaction and stores it in `offers.task_id`.
- The limit is enforced by the API (`db/tasks.op_budget`, called from `_enqueue`), only for ops whose payload carries `task_id`; omitting `task_id` skips the limit entirely (popped before validation, so the op schemas and `client.create_op` are unchanged). The task must be running, on the same canvas, the op type allowed by the mode and the count of its ops below the limit. A retried POST with the same `op_id` is not counted twice. Hypothesis, acceptable for now: a runner that omits its id is not stopped; the prompt tells it the id, it has no vault write and no Bash, and every draft needs Accept. Follow-up if it matters: a per-task MCP environment.
- The budget check runs inside `create_op`'s write lock together with the insert (which stores `task_id`), so parallel calls cannot overshoot.
- A claim expires after 15 minutes (`CLAIM_TTL_S`, hypothesis): `running` tasks older than that go back to `pending` when tasks are listed, claimed or picked by the runner, so a client that died does not hold a task forever.
- Pull path: MCP `list_tasks`, `claim_task`, `complete_task`. A question task cannot be completed `done` before its question is answered; `answer_question` finishes it. The runner takes a question only while its task is still `pending`, so a pull client's claim wins.
- Runner: questions first, then the oldest non-question task. Per-mode tool lists (`MODE_TOOLS`); every inkbridge write tool not in the mode is denied by name, so `create_canvas` is always denied. Vault tools only for `question` and `link`. A failed runner task goes back to `pending` with backoff and becomes `failed` after 3 tries; a failed question task goes back to `pending` and its give-up stays in `runner_status`. API start resets `running` runner tasks to `pending`.
- Daily cap: `INKBRIDGE_AGENT_DAILY_TASKS` (default 30, `0` = none, invalid warns and means 30) counts runner-claimed tasks that are not questions in the last 24 h. Questions the user asks are exempt. A capped task stays `pending` for the pull path.
- Each claim, finish and failure publishes `task.status {task_id, kind, status, line}` over the WebSocket.
- The class name `AskWorker` and the file name stay. `link_chunks` is named in the link mode but is not built yet; an unknown tool name in an allow-list is harmless.

## Consequences
The browser shows the line later (UI ticket). Cap and limits are hypotheses; revisit after a week of use.
