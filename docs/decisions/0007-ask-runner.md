# 0007: Ask runner (INK-048)

Status: accepted, 4 Nov 2026. 0007 was reserved for the INK-046 spike, which was waived (0035); it
now holds the runner decision.

1. **Where it runs.** `ask_runner.AskWorker` is a daemon thread in the API process with its own
   `db.connect()`, like the recognition worker. It polls for `pending` questions (not WebSocket
   triggered) so a restart picks up old rows. `INKBRIDGE_RUNNER` unset means no worker: the pull
   path of 0035 is unchanged. An unknown name or bad config logs a warning and leaves the worker
   off; the API always starts.
2. **Why Claude Code headless.** `claude -p` uses the user's own login, so no key is stored. The
   prompt goes on stdin (not argv: no leak in `ps`, no length limit). The child reaches the API
   only through the MCP server and its own `answer_question` call, so the transition guard of 0035
   is the only writer. Anything the model prints is discarded.
3. **Allow-list** (vault tool matching and failure reporting: decision 0060). A page or a vault note can contain instructions (prompt injection) and the
   backend never writes the vault. The command has `--strict-mcp-config`, an explicit
   `--allowedTools` (`read_canvas`, `get_region`, `search`, `answer_question`, plus vault tools from
   `INKBRIDGE_RUNNER_VAULT_TOOLS`) and a `--disallowedTools` list (Bash, Edit, Write, web, and the
   `write_text`, `draw_diagram`, `create_canvas` tools). Vault tool names containing a write word
   must start with search, read, get or list and contain no write word, or startup refuses them; the user must still curate the list. The child also gets `--permission-mode dontAsk` and `--setting-sources ""` (ambient user/project settings cannot widen the allow-list), an empty temp directory as cwd, and only PATH, HOME, LANG, LC_*, XDG_*, ANTHROPIC_* and CLAUDE_* from the environment. `terminate()` sets a flag under a lock held across Popen, so a shutdown cannot leak a child. Never a permission
   bypass. The prompt labels question, history, canvas and note text as untrusted.
4. **Focus.** The prompt uses `focus_chunk_ids` from `get_question()` at start time (0035 point 1).
   The size of `read_canvas` output is capped by 0018.
5. **Failure.** The row stays `pending`: nothing in this code can move it. A raise, a nonzero exit,
   a timeout (`INKBRIDGE_RUNNER_TIMEOUT_S`, default 180) or a clean exit without an answer counts
   as a failure. Failures are counted in memory per question: backoff `30s * attempts`, skipped
   after 3 until restart. The child runs in its own process group and is killed with the group on
   timeout and on API shutdown. `GEMINI_API_KEY` is removed from its environment. Only question id,
   exit code and binary name are logged, never stderr, prompt or paths.
6. **Limits.** One thread, one question at a time across all canvases (stricter than one per
   canvas); a slow question delays the others by at most the timeout. No session resume (never
   depend on it, CLAUDE.md). Another adapter is one `RUNNERS` entry plus its class.

## Manual check (not CI)
With the real `claude`, an MCP config naming the inkbridge stdio server (`INKBRIDGE_RUNNER_MCP_CONFIG`),
a test canvas, `INKBRIDGE_RUNNER=claude`, and a throwaway `INKBRIDGE_DB`: ask a question and see it
`answered`. Confirm the flag spellings with `claude --help` (especially `--permission-mode dontAsk` and an empty `--setting-sources`; the CI fake cannot check them) (adjust `build_command` and its test
together). Then `INKBRIDGE_RUNNER_TIMEOUT_S=1`: the row stays `pending` and `pgrep claude` is empty.
