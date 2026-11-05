# 0060 Ask runner: vault tool names, visible failures, Gemini 503 (INK-103)

Status: accepted.

## Decisions
1. **Vault verb is a whole word anywhere in the tool name.** `VAULT_VERB` is `(^|_)(search|read|get|list)(_|$)` used with `.search`, not `.match`, so `obsidian_search` and `obsidian_read_note` pass while `research` and `budget` do not. `save` joins the write words (`obsidian_save_note`, `obsidian_search_and_save`). A tool still needs a verb word AND the absence of every write word (substring check, unchanged); the refusal message names the tool. A harmless name containing a write word (for example `read_updates`) stays refused.
2. **Runner state lives on the question.** Migration 0006 adds `questions.runner_status` (`pending|running|failed`) and `runner_error` (at most 200 chars). They reach the API, `list_questions` and the WS `question.update`. They are only meaningful while `status='pending'` (an answered row is not touched, and the update is guarded on `pending`). Attempts 1 and 2 that fail show `pending` plus the last reason; attempt 3 shows `failed`. `running` is set while the child runs.
3. **Reset at API start.** Failure counts are in memory, so on start every pending question is reset to `pending` (or `failed` with the reason when the runner config is refused).
4. **Config refusal is visible.** If `INKBRIDGE_RUNNER` is set but unusable (unknown name, missing config, a write tool in the vault list), `AskWorker.setup` returns the reason instead of one log line; existing pending questions and every question created afterwards are marked `failed` with it. No runner is started.
5. **Reasons are path-free.** `RunnerError` texts ("exit 2", "timeout after 180s") and `returned without answering` are stored; any other exception stores only its class name. Stderr is never stored.
6. **`ServiceUnavailable` pauses the Gemini recognition worker** like a 429 or timeout. Gemini 503 maps to it; no retry inside the call (an outage outlasts call retries, the worker pause is the retry).
7. **Config note.** `INKBRIDGE_RUNNER_MCP_CONFIG` (for example `data/runner-mcp.json`) must define both the inkbridge server and the vault server, because the child runs with `--strict-mcp-config` and sees no other server. Names in `INKBRIDGE_RUNNER_VAULT_TOOLS` are `mcp__<server key in that file>__<tool>`.

## Rejected
- A `runner_runs` table: one runner and one state per question is enough.
- Retrying a 503 inside the call.
